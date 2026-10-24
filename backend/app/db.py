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
            tables = {
                row[0]
                for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            if "orders" in tables:
                cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(orders)").fetchall()}
                if "identity_postcode" not in cols:
                    conn.exec_driver_sql("ALTER TABLE orders ADD COLUMN identity_postcode VARCHAR")
                conn.exec_driver_sql(
                    "UPDATE orders SET identity_postcode = postcode "
                    "WHERE identity_postcode IS NULL OR identity_postcode = ''"
                )


def session() -> Session:
    if SessionLocal is None:
        raise RuntimeError("Database is not configured")
    return SessionLocal()


def engine():
    return _engine
