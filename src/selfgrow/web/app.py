"""Web 服务：FastAPI 路由 + SSE 实时推流 + 静态前端。

入口：`python -m selfgrow.web.app`（127.0.0.1:8000，本地演示服务）。
REST / SSE 协议见 sessions.py 与 docs/architecture.md。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from selfgrow.competency.loader import load_framework
from selfgrow.llm.base import get_llm
from selfgrow.paths import ensure_data_dirs
from selfgrow.web.sessions import (
    AnswerValidationError,
    SessionBusyError,
    SessionLimitError,
    SessionManager,
    SessionNotFoundError,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_DOMAIN = "managing_up"


def create_app(manager: SessionManager | None = None) -> FastAPI:
    """应用工厂：测试注入内存版 SessionManager，默认用全局 manager。"""
    m = manager or SessionManager()
    app = FastAPI(title="SelfGrowAgent Web", version="0.1.0")
    app.state.manager = m

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        """前端元数据：能力框架（维度顺序/中文名/5 级锚定）+ 当前模型模式。"""
        fw = load_framework(DEFAULT_DOMAIN)
        return {
            "domain": fw.domain,
            "name": fw.name,
            "description": fw.description,
            "scale": fw.scale,
            "dimensions": [d.to_dict() for d in fw.dimensions],
            "llm_mode": get_llm().mode,
        }

    @app.post("/api/sessions", status_code=201)
    async def create_session(req: Request) -> dict[str, str]:
        body = await _json_or(req, {})
        goal = str(body.get("goal") or "").strip()
        try:
            s = m.create(goal)
        except SessionLimitError as exc:
            raise HTTPException(503, str(exc))
        return {"session_id": s.id, "status": s.status}

    @app.get("/api/sessions/{sid}")
    def session_state(sid: str) -> dict[str, Any]:
        return _get(m, sid).state_dict()

    @app.get("/api/sessions/{sid}/events")
    async def events(sid: str, request: Request) -> StreamingResponse:
        """SSE：先重放历史，再实时推流（心跳保活），done/error 后关闭。"""
        s = _get(m, sid)
        return StreamingResponse(
            s.iterate(request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/sessions/{sid}/answer")
    async def answer(sid: str, req: Request) -> dict[str, bool]:
        s = _get(m, sid)
        try:
            s.submit_answer(await _json_or(req, {}))
        except AnswerValidationError as exc:
            raise HTTPException(400, str(exc))
        except SessionBusyError as exc:
            raise HTTPException(409, str(exc))
        return {"ok": True}

    @app.post("/api/sessions/{sid}/cancel")
    def cancel(sid: str) -> dict[str, bool]:
        _get(m, sid).cancel()
        return {"ok": True}

    return app


def _get(m: SessionManager, sid: str):
    try:
        return m.get(sid)
    except SessionNotFoundError as exc:
        raise HTTPException(404, str(exc))


async def _json_or(req: Request, default: Any) -> Any:
    """容错解析 JSON body（空 body/坏 JSON → 默认值，走正常校验报 400）。"""
    try:
        return await req.json()
    except Exception:
        return default


app = create_app()


def main() -> None:
    """启动本地服务（不开 reload，避免 Windows 多进程重复构建 RAG）。"""
    ensure_data_dirs()
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
