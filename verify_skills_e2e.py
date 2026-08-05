"""端到端验证：驱动真实 root_agent（经 ADK Runner），逐一真实调用 9 类能力。

对每条 prompt：
- 记录本轮 agent 实际发起的 function_call 名称与参数；
- 记录对应 function_response（工具真实返回）；
- 打印精简结论，证明「该能力可用，且被 agent 真实调用」。

注意：image/video 为真实生成，会有少量费用与耗时（已获用户同意）。
"""

import asyncio
import json
import sys
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from assistant import root_agent

APP = "movie_script_agent"
USER = "verify_user"


def _summarize(obj, limit=600):
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    return s if len(s) <= limit else s[:limit] + "…(truncated)"


async def run_prompt(runner, session_id, label, prompt):
    print("\n" + "=" * 78)
    print(f"[{label}] PROMPT: {prompt}")
    content = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
    calls = []
    responses = []
    final_text = []
    async for event in runner.run_async(
        user_id=USER, session_id=session_id, new_message=content
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            fc = getattr(part, "function_call", None)
            fr = getattr(part, "function_response", None)
            if fc:
                calls.append((fc.name, dict(fc.args or {})))
                print(f"  -> CALL {fc.name} args={_summarize(dict(fc.args or {}), 300)}")
            if fr:
                resp = fr.response
                responses.append((fr.name, resp))
                print(f"  <- RESP {fr.name}: {_summarize(resp, 500)}")
            txt = getattr(part, "text", None)
            if txt and not getattr(part, "thought", False):
                final_text.append(txt)
    tool_names = [c[0] for c in calls]
    print(f"  == tools called: {tool_names}")
    return {"label": label, "calls": calls, "responses": responses,
            "text": "\n".join(final_text).strip()}


PROMPTS = [
    ("web_search", "请用网页搜索工具，联网搜索『2024 年戛纳电影节金棕榈奖得主』，"
                   "并给我搜索到的关键结果与来源。必须真实调用 web_search。"),
    ("web_fetch", "请用网页读取工具读取 https://example.com 的正文内容，"
                  "告诉我页面标题和主要文字。必须真实调用 web_fetch 或 link_reader。"),
    ("image_generate", "用 Seedream 生成一张图片：一位侦探站在雨夜霓虹街头的电影分镜概念图，"
                       "赛博朋克风格。必须真实调用 image_generate，并给我返回的图片链接。"),
    ("video_generate", "用 Seedance 生成一段约 5 秒的短视频：雨滴落在窗户上的电影空镜，"
                       "缓慢推镜。必须真实调用 video_generate，并告诉我任务/视频返回信息。"),
    ("run_code", "请用 run_code 在 AgentKit 沙箱里执行一段 Python，计算 1 到 100 的和并打印结果。"
                 "必须真实调用 run_code，并告诉我打印出来的数值。"),
    ("create_document_docx", "请用 create_document 生成一个 Word 文档，doc_format=docx，"
                             "filename=verify_scene.docx，title=场景一，"
                             "content 里写：# 场景一\\n- 时间：雨夜\\n- 地点：霓虹街头\\n侦探独自前行。"
                             "然后用 read_document 读回该文件内容确认。"),
    ("create_document_pdf", "请用 create_document 生成一个 PDF，doc_format=pdf，"
                            "filename=verify_scene.pdf，title=场景一PDF，content 写两三行剧本说明，"
                            "然后用 read_document 读回并告诉我 PDF 里的文字与页数。"),
    ("create_document_pptx", "请用 create_document 生成一个 PPT，doc_format=pptx，"
                             "filename=verify_deck.pptx，content 写：# 第一页 概述\\n- 要点A\\n- 要点B\\n"
                             "# 第二页 角色\\n- 侦探\\n- 反派。然后 read_document 读回确认页面文字。"),
    ("create_document_html", "请用 create_document 生成一个 HTML，doc_format=html，"
                             "filename=verify_page.html，title=剧本网页，content 写一个标题和两段说明，"
                             "然后 read_document 读回确认其中的文字。"),
]


async def main():
    session_service = InMemorySessionService()
    runner = Runner(
        app_name=APP, agent=root_agent, session_service=session_service
    )
    results = []
    # 关键：所有 prompt 共用「同一个」ADK session。
    # 因为内置 run_code 与 create_document/read_document 都按
    #   agent_name + "_" + user_id + "_" + <adk_session_id>
    # 派生 sandbox 的 tool_user_session_id，共用一个 ADK session 就能把 5 条会触发
    # 沙箱的调用收敛到「同一个」sandbox session（仅占用 1 个并发会话），
    # 从而规避沙箱 2 并发会话的配额限制（CreateSessionFailed）。
    sid = f"verify-all-{uuid.uuid4().hex[:8]}"
    await session_service.create_session(app_name=APP, user_id=USER, session_id=sid)
    for label, prompt in PROMPTS:
        try:
            res = await run_prompt(runner, sid, label, prompt)
        except Exception as e:  # noqa: BLE001
            print(f"  !! ERROR during {label}: {e!r}")
            res = {"label": label, "calls": [], "responses": [], "error": repr(e)}
        results.append(res)

    print("\n\n" + "#" * 78)
    print("# 验证结果汇总")
    print("#" * 78)
    for r in results:
        tools = [c[0] for c in r.get("calls", [])]
        ok = bool(tools) and "error" not in r
        print(f"[{'OK ' if ok else 'CHK'}] {r['label']:<24} tools={tools}")


if __name__ == "__main__":
    asyncio.run(main())
