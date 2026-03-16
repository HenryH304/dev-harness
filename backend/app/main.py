from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import AppConfig, load_config
from app.database import get_engine, init_db
from app.redis_client import close_redis
from app.routers.agents import router as agents_router
from app.routers.dashboard import router as dashboard_router
from app.routers.dependencies import deps_router
from app.routers.dependencies import router as dependencies_router
from app.routers.notes import router as notes_router
from app.routers.projects import router as projects_router
from app.routers.settings import router as settings_router
from app.routers.tickets import router as tickets_router
from app.routers.transitions import router as transitions_router
from app.websocket import manager, redis_listener

config: AppConfig = load_config()
engine = get_engine()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Run database migrations on startup and start Redis listener."""
    import asyncio

    await init_db(engine)
    listener_task = asyncio.create_task(redis_listener())
    yield
    listener_task.cancel()
    await close_redis()
    await engine.dispose()


app = FastAPI(title="DevHarness", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(tickets_router)
app.include_router(dashboard_router)
app.include_router(dependencies_router)
app.include_router(deps_router)
app.include_router(notes_router)
app.include_router(transitions_router)
app.include_router(agents_router)
app.include_router(projects_router)
app.include_router(settings_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time board updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, listen for client messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


def get_port() -> int:
    return config.port


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=get_port())
