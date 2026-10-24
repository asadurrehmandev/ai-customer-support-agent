"""Keel API."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import delete, func, select

from app.agent.engine import Agent
from app.api.routes import router
from app.commerce.routed import RoutedCommerce
from app.config import DATA_DIR, Settings
from app.db import configure, init_schema, session
from app.kb.index import SearchIndex
from app.kb.ingest import seed_knowledge
from app.models import Article, Chunk, Conversation, Order
from app.seed.store import seed_store
from app.seed.traffic import seed_traffic
from app.textutil import redact

WIDGET_PATH = Path(__file__).resolve().parent / "widget" / "keel.js"


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(redact(arg) if isinstance(arg, str) else arg for arg in record.args)
        return True


def _install_redaction() -> None:
    filt = RedactFilter()
    logging.getLogger().addFilter(filt)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addFilter(filt)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _install_redaction()
    settings = Settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    configure(settings.database_url)
    init_schema()
    db = session()
    try:
        if not db.scalar(select(func.count()).select_from(Order)):
            seed_store(db)
        sample = db.scalar(select(Chunk.embed_text).limit(1))
        if sample and not str(sample).startswith("v2\n"):
            db.execute(delete(Chunk))
            db.execute(delete(Article))
            db.commit()
        if not db.scalar(select(func.count()).select_from(Article)):
            seed_knowledge(db, DATA_DIR / "corpus")
        index = SearchIndex()
        index.load_or_build(db)
        commerce = RoutedCommerce(settings)
        app.state.settings = settings
        app.state.index = index
        app.state.commerce = commerce
        app.state.agent = Agent(commerce, index, settings)
        if not settings.skip_traffic and not db.scalar(select(func.count()).select_from(Conversation)):
            seed_traffic(db, app.state.agent)
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Keel", version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.get("/widget/keel.js")
    def widget_script():
        return PlainTextResponse(
            WIDGET_PATH.read_text(encoding="utf-8"),
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache"},
        )

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if frontend.exists():
        @app.get("/")
        def index():
            return FileResponse(frontend / "index.html")

    return app


app = create_app()
