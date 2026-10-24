from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

class Base(DeclarativeBase):
    pass


_engine = None
SessionLocal: sessionmaker[Session] | None = None


def configure(url: str):
    global _engine, SessionLocal
    if _engine is not None:
        _engine.dispose()
    connect: dict = {}
    if url.startswith("sqlite"):
        connect["check_same_thread"] = False
    _engine = create_engine(url, connect_args=connect)
    SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def init_schema() -> None:
    from app import models  # noqa: F401

    assert _engine is not None
    Base.metadata.create_all(_engine)
    if str(_engine.url).startswith("sqlite"):
        with _engine.begin() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")


def session() -> Session:
    if SessionLocal is None:
        raise RuntimeError("Database is not configured")
    return SessionLocal()


def engine():
    return _engine
