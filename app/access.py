"""云端准入：使用签名 Cookie，保护页面、静态资源及 API。"""
import hashlib
import hmac
import time
import uuid
import re
from http.cookies import SimpleCookie
from urllib.parse import parse_qs

from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from .storage import Conflict

import config

LOGIN = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Movie Agent · 登录 / Sign in</title>
<style>body{background:#111820;color:#eef2f7;font:16px Arial;margin:0;display:grid;
place-items:center;min-height:100vh}form{padding:32px;max-width:340px}
input,button{box-sizing:border-box;width:100%;padding:14px;margin:8px 0;
border-radius:8px;border:1px solid #657080}button{background:#a9ceff;cursor:pointer}
p{line-height:1.6}</style><form method="post" action="/login">
<h1>Movie Agent</h1><p>请输入准入密码<br>Enter the access password</p>
<label for="password">密码 / Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" required>
<button>登录 / Sign in</button><p role="alert">ERROR_MESSAGE</p></form></html>"""


class BrowserTasks:
    """Signed browser identity and authorization for every task route."""
    def __init__(self, app, store):
        self.app, self.store = app, store
        self.secret = (config.WEBUI_SESSION_SECRET or uuid.uuid4().hex).encode()

    def sign(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cookies = SimpleCookie()
        try:
            cookies.load(dict(scope["headers"]).get(b"cookie", b"").decode())
            owner, signature = cookies["movieagent_browser"].value.split(".")
            valid = bool(re.fullmatch(r"[a-f0-9]{32}", owner)) and hmac.compare_digest(signature, self.sign(owner))
        except (KeyError, ValueError):
            valid = False
        if not valid:
            owner = uuid.uuid4().hex
        scope.setdefault("state", {})["owner"] = owner

        async def identity_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                if not valid:
                    value = f"movieagent_browser={owner}.{self.sign(owner)}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Strict"
                    if config.WEBUI_CLOUD_MODE:
                        value += "; Secure"
                    headers.append((b"set-cookie", value.encode()))
                if scope["path"].startswith("/api/"):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        token, sid = None, None
        match = re.match(r"^/api/sessions/([^/]+)(?:/|$)", scope["path"])
        try:
            if match:
                sid = match[1]
                if not re.fullmatch(r"[a-f0-9]{32}", sid) or not await run_in_threadpool(self.store.load_owned, owner, sid):
                    return await JSONResponse({"detail": "session not found"}, 404)(scope, receive, identity_send)
                operation = scope["path"].split(f"/{sid}", 1)[1]
                if scope["method"] in ("POST", "PATCH", "DELETE") and operation not in (
                    "/stop", "/close", "/heartbeat", "/speech",
                ):
                    scope["state"]["generation_deadline"] = time.monotonic() + 720
                    token = await run_in_threadpool(self.store.claim, sid, operation)
            await self.app(scope, receive, identity_send)
        except Conflict:
            await JSONResponse({"detail": "正文生成中，请勿重复提交。"}, 409)(scope, receive, identity_send)
        finally:
            if token:
                await run_in_threadpool(self.store.release, sid, token)


class CloudAccess:
    def __init__(self, app):
        self.app = app
        self.failures = {}

    def signature(self, expiry):
        return hmac.new(
            config.WEBUI_SESSION_SECRET.encode(), expiry.encode(), hashlib.sha256
        ).hexdigest()

    async def __call__(self, scope, receive, send):
        if not config.WEBUI_CLOUD_MODE or scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get(b"cookie", b"").decode())
            expiry, signature = cookie["movieagent_access"].value.split(".")
            valid = int(expiry) > time.time() and hmac.compare_digest(signature, self.signature(expiry))
        except (KeyError, ValueError):
            valid = False
        path = scope["path"]
        if path == "/login":
            if scope["method"] == "POST":
                # 按客户端限流，避免反复尝试密码。
                client = scope.get("client") or ("unknown", 0)
                address = headers.get(b"x-forwarded-for", str(client[0]).encode()).decode().split(",")[0]
                count, until = self.failures.get(address, (0, 0))
                if until <= time.time():
                    count = 0
                body = b""
                while True:
                    message = await receive()
                    body += message.get("body", b"")
                    if len(body) > 4096:
                        return await JSONResponse({"detail": "Invalid request"}, 413)(scope, receive, send)
                    if not message.get("more_body"):
                        break
                password = parse_qs(body.decode()).get("password", [""])[0]
                if count >= 10:
                    response = HTMLResponse(LOGIN.replace("ERROR_MESSAGE", "请稍后重试 / Try later"), 429)
                elif hmac.compare_digest(password.encode(), config.WEBUI_ACCESS_PASSWORD.encode()):
                    self.failures.pop(address, None)
                    expiry = str(int(time.time()) + 43200)
                    response = RedirectResponse("/", 303)
                    response.set_cookie("movieagent_access", expiry + "." + self.signature(expiry),
                                        max_age=43200, httponly=True, secure=True, samesite="strict")
                else:
                    self.failures[address] = (count + 1, time.time() + 300)
                    response = HTMLResponse(LOGIN.replace("ERROR_MESSAGE", "密码错误 / Incorrect password"), 401)
            else:
                response = HTMLResponse(LOGIN.replace("ERROR_MESSAGE", ""))
            response.headers["Cache-Control"] = "no-store"
            return await response(scope, receive, send)
        if not valid:
            response = JSONResponse({"detail": "Sign in required"}, 401) if path.startswith("/api/") else RedirectResponse("/login", 303)
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)
