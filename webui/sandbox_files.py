"""从 AgentKit sandbox 里把文档文件读成 bytes —— 供 BFF 下载 Agent 生成的 docx/pdf/pptx/html。

背景：
- 图片/视频工具返回的是「公网 URL」，前端可直接 <img>/<video> 或下载；
- 但 create_document 只返回沙箱内路径（/home/gem/veadk_docs/xxx），文件在 AgentKit
  sandbox 里，浏览器拿不到。此模块用 RunCode 在同一个沙箱会话里把文件 base64 读出来。

关键：沙箱会话 id 的派生规则与 document_tools 一致：
    tool_user_session_id = f"{agent_name}_{user_id}_{session_id}"
只要 BFF 用与聊天相同的 (agent_name, user_id, session_id)，就能定位到同一个沙箱、读到同一批文件。

只依赖标准库 + requests（VeFaaS 原生 python 运行时已有 requests），不引入整包 veadk。
"""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
import os
from typing import Optional
from urllib.parse import quote

import requests

_SANDBOX_DOC_DIR = "/home/gem/veadk_docs"
_SERVICE = "agentkit"
_VERSION = "2025-10-30"


def _sign_and_request(
    *, ak: str, sk: str, region: str, host: str, action: str, body: dict,
    scheme: str = "https", timeout: tuple = (10, 120),
) -> dict:
    """最小化的火山 SigV4（Action/Version query 风格），等价于 veadk.ve_request。"""
    now = datetime.datetime.utcnow()
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    payload = json.dumps(body)
    content_sha = hashlib.sha256(payload.encode()).hexdigest()
    query = {"Action": action, "Version": _VERSION}

    def _norm_query(params):
        q = ""
        for k in sorted(params):
            q += quote(k, safe="-_.~") + "=" + quote(params[k], safe="-_.~") + "&"
        return q[:-1].replace("+", "%20")

    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical = "\n".join([
        "POST", "/", _norm_query(query),
        "\n".join([
            "content-type:application/json",
            "host:" + host,
            "x-content-sha256:" + content_sha,
            "x-date:" + x_date,
        ]),
        "", signed_headers, content_sha,
    ])
    scope = "/".join([short_date, region, _SERVICE, "request"])
    to_sign = "\n".join(["HMAC-SHA256", x_date, scope,
                         hashlib.sha256(canonical.encode()).hexdigest()])

    def _hmac(key, msg):
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    k = _hmac(sk.encode(), short_date)
    k = _hmac(k, region)
    k = _hmac(k, _SERVICE)
    k = _hmac(k, "request")
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()

    headers = {
        "Host": host, "X-Date": x_date, "X-Content-Sha256": content_sha,
        "Content-Type": "application/json",
        "Authorization": f"HMAC-SHA256 Credential={ak}/{scope}, "
                         f"SignedHeaders={signed_headers}, Signature={sig}",
    }
    r = requests.request("POST", f"{scheme}://{host}/", headers=headers,
                         params=query, data=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


# 在沙箱里执行的读取脚本：把目标文件按 base64 打印出来（带标记行，抗噪音）。
_READ_SCRIPT = r'''
import base64, json, os
p = json.loads(base64.b64decode("__P__").decode())["path"]
res = {"ok": False}
try:
    if os.path.exists(p):
        with open(p, "rb") as f:
            data = f.read()
        res = {"ok": True, "path": p, "size": len(data),
               "b64": base64.b64encode(data).decode("ascii")}
    else:
        res = {"ok": False, "error": "not found: %s" % p}
except Exception as e:
    res = {"ok": False, "error": repr(e)}
print("FILE_B64_JSON:" + json.dumps(res))
'''


def _extract_marker(resp: dict, marker: str) -> Optional[dict]:
    """从 InvokeTool 返回体里抽取脚本 stdout 的标记行 JSON。"""
    if not isinstance(resp, dict) or "Result" not in resp:
        api_err = (resp.get("ResponseMetadata") or {}).get("Error") or {}
        raise RuntimeError(f"AgentKit error: {api_err or str(resp)[:200]}")
    payload = json.loads(resp["Result"]["Result"])
    stdout = ""
    for out in payload.get("data", {}).get("outputs", []) or []:
        if isinstance(out, dict) and out.get("text"):
            stdout += out["text"]
    for line in stdout.splitlines():
        idx = line.find(marker)
        if idx != -1:
            return json.loads(line[idx + len(marker):].strip())
    return None


def read_sandbox_file(
    *, path: str, agent_name: str, user_id: str, session_id: str,
    tool_id: Optional[str] = None,
) -> dict:
    """读取沙箱里某文件，返回 {ok, path, size, data(bytes)} 或 {ok: False, error}。

    session 派生必须与 document_tools._sandbox_session_id 完全一致。
    """
    ak = os.getenv("VOLCENGINE_ACCESS_KEY")
    sk = os.getenv("VOLCENGINE_SECRET_KEY")
    if not (ak and sk):
        return {"ok": False, "error": "VOLCENGINE_ACCESS_KEY/SECRET_KEY not set"}

    tool_id = tool_id or os.getenv("AGENTKIT_TOOL_ID_SCRIPT") or os.getenv("AGENTKIT_TOOL_ID")
    if not tool_id:
        return {"ok": False, "error": "AGENTKIT_TOOL_ID(_SCRIPT) not set"}

    region = os.getenv("AGENTKIT_TOOL_REGION", "cn-beijing")
    host = os.getenv("AGENTKIT_TOOL_HOST", f"{_SERVICE}.{region}.volces.com")

    # 只允许读文档目录，避免任意路径读取。
    safe_path = path if os.path.isabs(path) else os.path.join(_SANDBOX_DOC_DIR, path)
    if not safe_path.startswith(_SANDBOX_DOC_DIR):
        return {"ok": False, "error": f"path not allowed: {safe_path}"}

    p_b64 = base64.b64encode(json.dumps({"path": safe_path}).encode()).decode()
    code = _READ_SCRIPT.replace("__P__", p_b64)
    sandbox_session = f"{agent_name}_{user_id}_{session_id}"

    resp = _sign_and_request(
        ak=ak, sk=sk, region=region, host=host, action="InvokeTool",
        body={
            "ToolId": tool_id,
            "UserSessionId": sandbox_session,
            "OperationType": "RunCode",
            "OperationPayload": json.dumps(
                {"code": code, "timeout": 120, "kernel_name": "python3"}
            ),
        },
    )
    result = _extract_marker(resp, "FILE_B64_JSON:")
    if result is None:
        return {"ok": False, "error": "no file payload from sandbox"}
    if not result.get("ok"):
        return result
    return {
        "ok": True,
        "path": result["path"],
        "size": result["size"],
        "data": base64.b64decode(result["b64"]),
    }
