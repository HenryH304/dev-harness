from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import AppConfig, load_config
from app.database import get_engine, init_db
from app.routers.dependencies import router as dependencies_router
from app.routers.notes import router as notes_router
from app.routers.tickets import router as tickets_router

config: AppConfig = load_config()
engine = get_engine()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Run database migrations on startup."""
    await init_db(engine)
    yield
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
app.include_router(dependencies_router)
app.include_router(notes_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def get_port() -> int:
    return config.port


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=get_port())
