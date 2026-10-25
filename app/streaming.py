"""Keep an active streaming HTTP request visible while its model is thinking."""
from __future__ import annotations

import asyncio
import json
import time

import anyio
from starlette.concurrency import run_in_threadpool

HEARTBEAT_SECONDS = 10
_END = object()


async def with_heartbeats(source, on_disconnect, on_heartbeat=None):
    """Advance a synchronous generator once at a time within this request.

    The worker is always joined before the request lease is released; it is not
    an independent background job. A heartbeat prevents idle silence, while the
    caller's deadline still bounds the gateway's absolute request duration.
    """
    pending = None
    began = time.monotonic()
    finished = False
    try:
        while True:
            pending = asyncio.create_task(run_in_threadpool(next, source, _END))
            while not pending.done():
                ready, _ = await asyncio.wait({pending}, timeout=HEARTBEAT_SECONDS)
                if not ready:
                    elapsed = round(time.monotonic() - began)
                    if on_heartbeat:
                        on_heartbeat(elapsed)
                    yield json.dumps({"type": "heartbeat", "elapsed_seconds": elapsed}) + "\n"
            event = pending.result()
            pending = None
            if event is _END:
                finished = True
                return
            yield event
    finally:
        if not finished:
            on_disconnect()
        # Starlette cancels on disconnect. Shield cleanup so the model worker
        # cannot outlive the request and write after another browser resumes.
        with anyio.CancelScope(shield=True):
            if pending is not None:
                try:
                    await asyncio.shield(pending)
                except Exception:
                    pass
            await run_in_threadpool(source.close)
