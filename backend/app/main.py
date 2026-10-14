from fastapi import FastAPI
from sqlalchemy import text

from .db import Base, engine
from . import models  # noqa: F401 - registers ORM models before table creation


app = FastAPI(
    title="Dynamic Adaptive AI Agent Workflow",
    version="0.1.0",
)


@app.on_event("startup")
def create_tables() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}

