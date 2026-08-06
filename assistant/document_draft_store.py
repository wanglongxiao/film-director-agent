# Copyright (c) 2026 Alex Wang
# @author Alex Wang <https://github.com/wanglongxiao>
# @contact https://www.linkedin.com/in/alexwanglx/
# Open Source Usage: attribution required; preserve this notice in redistributions.

"""文档草稿存储 —— 把「剧本片段 + 生成图片」增量落盘到本地 sqlite，最后一次性组装。

这是为了解决「单一任务（单次 LLM 交互）超过 MAX tokens 而不能完成」的核心设施：

- 传统做法要求 Agent 在最后一步把「整份剧本正文」作为 create_document 的 content 参数
  一次性重新输出，长剧本必然超单轮 max_output_tokens 而被截断，且 function_call 参数
  无法续写，只能从头重做 —— 于是陷入「继续 → 又撞 MAX tokens」的死循环。
- 本模块让 Agent 每生成一小段剧本/一张图，就调用工具把它 **增量写入本地 sqlite**
  （每次都是小片段，永不超输出预算）。所有片段按插入顺序（seq）记录，天然支持
  「文字 + 图片」混编。最终由 Python 从 sqlite 读回全部片段，在服务端拼成完整 HTML
  再交给沙箱转 PDF —— LLM 在组装步骤只传 draft_id/标题/格式等小参数，完全不碰大文本。

一份「草稿」由 (app_name, user_id, session_id, draft_id) 唯一确定；同一会话可用不同
draft_id 维护多份文档草稿，默认 draft_id="default"。
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path


_DEFAULT_DB_PATH = os.getenv(
    "VEADK_DOC_DRAFT_DB_PATH", "/tmp/movie_script_doc_draft.db"
)

# 组装 PDF 时是否把远程图片下载并内联为 base64（默认开）。沙箱内 weasyprint 常常无法
# 联网拉取带签名的临时 URL，导致「图片不进 PDF」；改在服务端（有网、URL 未过期时）预下载
# 内联，PDF 即自包含图片。下载失败则回退为原始 URL，交给渲染端尽力拉取。
_INLINE_IMAGES = os.getenv("VEADK_DOC_INLINE_IMAGES", "1").strip().lower() not in ("0", "false", "no")
_IMAGE_DOWNLOAD_TIMEOUT = float(os.getenv("VEADK_DOC_IMAGE_TIMEOUT", "20"))
_IMAGE_MAX_BYTES = int(os.getenv("VEADK_DOC_IMAGE_MAX_BYTES", str(12 * 1024 * 1024)))


def _image_url_to_data_uri(url: str) -> str | None:
    """下载图片并转为 base64 data URI；失败/超限返回 None（回退到原始 URL）。"""
    if not (isinstance(url, str) and url.lower().startswith(("http://", "https://"))):
        return None
    try:
        import base64

        import httpx

        with httpx.Client(timeout=_IMAGE_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.content
            if not data or len(data) > _IMAGE_MAX_BYTES:
                return None
            ctype = (resp.headers.get("content-type") or "").split(";")[0].strip()
            if not ctype.startswith("image/"):
                ctype = "image/jpeg"
            b64 = base64.b64encode(data).decode("ascii")
            return "data:%s;base64,%s" % (ctype, b64)
    except Exception:  # noqa: BLE001 - 下载失败即回退原始 URL
        return None


def _esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _section_body_to_html(body: str) -> str:
    """把「# / ## 标题、- 要点、普通段落」的轻量 markdown 片段转成 HTML。

    与沙箱脚本内 _lines_to_html_body 保持一致的规则，保证组装结果风格统一。
    """
    parts: list[str] = []
    in_ul = False
    for raw in (body or "").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("## "):
            if in_ul:
                parts.append("</ul>"); in_ul = False
            parts.append("<h3>%s</h3>" % _esc(line[3:].strip()))
        elif line.startswith("# "):
            if in_ul:
                parts.append("</ul>"); in_ul = False
            parts.append("<h2>%s</h2>" % _esc(line[2:].strip()))
        elif line.startswith("- ") or line.startswith("* "):
            if not in_ul:
                parts.append("<ul>"); in_ul = True
            parts.append("<li>%s</li>" % _esc(line[2:].strip()))
        else:
            if in_ul:
                parts.append("</ul>"); in_ul = False
            parts.append("<p>%s</p>" % _esc(line))
    if in_ul:
        parts.append("</ul>")
    return "\n".join(parts)


class DocumentDraftStore:
    """Persist interleaved document sections/images to local sqlite for later assembly."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ensure_parent_dir()
        self._init_db()

    def _ensure_parent_dir(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS doc_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    app_name TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    draft_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT DEFAULT '',
                    body TEXT DEFAULT '',
                    url TEXT DEFAULT '',
                    caption TEXT DEFAULT '',
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_doc_items_lookup
                ON doc_items (app_name, user_id, session_id, draft_id, seq)
                """
            )
            conn.commit()

    def _next_seq(self, conn, *, app_name, user_id, session_id, draft_id) -> int:
        row = conn.execute(
            """
            SELECT COALESCE(MAX(seq), 0) AS max_seq
            FROM doc_items
            WHERE app_name = ? AND user_id = ? AND session_id = ? AND draft_id = ?
            """,
            (app_name, user_id, session_id, draft_id),
        ).fetchone()
        return int(row["max_seq"]) + 1

    def add_item(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        draft_id: str,
        kind: str,
        title: str = "",
        body: str = "",
        url: str = "",
        caption: str = "",
    ) -> int:
        """Append one ordered item (section/image/pagebreak) to a draft; returns its seq."""
        with self._lock, self._connect() as conn:
            seq = self._next_seq(
                conn,
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                draft_id=draft_id,
            )
            conn.execute(
                """
                INSERT INTO doc_items (
                    app_name, user_id, session_id, draft_id, seq, kind,
                    title, body, url, caption, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    app_name,
                    user_id,
                    session_id,
                    draft_id,
                    seq,
                    kind,
                    title or "",
                    body or "",
                    url or "",
                    caption or "",
                    time.time(),
                ),
            )
            conn.commit()
            return seq

    def list_items(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        draft_id: str,
    ) -> list[dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT seq, kind, title, body, url, caption
                FROM doc_items
                WHERE app_name = ? AND user_id = ? AND session_id = ? AND draft_id = ?
                ORDER BY seq ASC, id ASC
                """,
                (app_name, user_id, session_id, draft_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def stats(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        draft_id: str,
    ) -> dict:
        items = self.list_items(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            draft_id=draft_id,
        )
        sections = [it for it in items if it["kind"] == "section"]
        images = [it for it in items if it["kind"] == "image"]
        total_chars = sum(len(it.get("body") or "") for it in sections)
        return {
            "draft_id": draft_id,
            "total_items": len(items),
            "sections": len(sections),
            "images": len(images),
            "total_chars": total_chars,
        }

    def clear(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        draft_id: str,
    ) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                DELETE FROM doc_items
                WHERE app_name = ? AND user_id = ? AND session_id = ? AND draft_id = ?
                """,
                (app_name, user_id, session_id, draft_id),
            )
            conn.commit()
            return cur.rowcount

    def assemble_html(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        draft_id: str,
        title: str = "",
    ) -> str:
        """Read all saved items in order and build one complete, printable HTML doc.

        文字片段渲染为标题/段落/要点，图片渲染为 <figure><img><figcaption>，页面分隔
        渲染为 CSS 分页符 —— 天然实现「剧本文字 + 分镜图」混编。整份 HTML 由 Python
        在服务端拼装，LLM 不需要重新输出任何长文本。
        """
        items = self.list_items(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            draft_id=draft_id,
        )
        blocks: list[str] = []
        if title:
            blocks.append("<h1>%s</h1>" % _esc(title))
        for it in items:
            kind = it.get("kind")
            if kind == "section":
                if it.get("title"):
                    blocks.append("<h2>%s</h2>" % _esc(it["title"]))
                body_html = _section_body_to_html(it.get("body") or "")
                if body_html:
                    blocks.append(body_html)
            elif kind == "image":
                url = (it.get("url") or "").strip()
                if not url:
                    continue
                caption = it.get("caption") or it.get("title") or ""
                # 优先内联为 base64，使 PDF 自包含图片；下载失败则回退原始 URL。
                src = url
                if _INLINE_IMAGES:
                    data_uri = _image_url_to_data_uri(url)
                    if data_uri:
                        src = data_uri
                fig = ['<figure class="doc-figure">']
                fig.append('<img src="%s" alt="%s" />' % (_esc(src), _esc(caption)))
                if caption:
                    fig.append("<figcaption>%s</figcaption>" % _esc(caption))
                fig.append("</figure>")
                blocks.append("\n".join(fig))
            elif kind == "pagebreak":
                blocks.append('<div class="page-break"></div>')

        body = "\n".join(blocks) if blocks else "<p>(空文档)</p>"
        return (
            "<!DOCTYPE html>\n<html lang=\"zh\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<title>%s</title>\n"
            "<style>\n"
            "body{font-family:'Noto Sans CJK SC','DejaVu Sans',sans-serif;"
            "margin:40px;line-height:1.7;color:#222}\n"
            "h1{border-bottom:3px solid #444;padding-bottom:8px}\n"
            "h2{color:#1a1a1a;margin-top:1.4em;border-left:4px solid #7c5cff;padding-left:10px}\n"
            "h3{color:#333;margin-top:1.1em}\n"
            "figure.doc-figure{margin:18px 0;text-align:center;page-break-inside:avoid}\n"
            "figure.doc-figure img{max-width:100%%;border:1px solid #ddd;border-radius:8px}\n"
            "figure.doc-figure figcaption{color:#666;font-size:0.9em;margin-top:6px}\n"
            ".page-break{page-break-after:always}\n"
            "ul{margin:0.4em 0 0.8em 1.2em}\n"
            "</style>\n</head>\n<body>\n%s\n</body>\n</html>"
            % (_esc(title or "Document"), body)
        )


document_draft_store = DocumentDraftStore()
