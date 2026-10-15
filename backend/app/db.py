from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from .config import settings


def build_engine(url: str, *, pooled: bool = False):
    if not url:
        raise ValueError("請在 backend/.env 設定 DATABASE_URL")
    options = {"pool_size": 2, "max_overflow": 0, "pool_timeout": 10} if pooled else {"poolclass": NullPool}
    return create_engine(
        url, pool_pre_ping=True, hide_parameters=True,
        connect_args={"connect_timeout": settings.db_connect_timeout}, **options,
    )


engine = build_engine(settings.database_url, pooled=settings.db_pool_mode == "queue")
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

