import redis
from fastapi import FastAPI
from sqlalchemy import create_engine, text

from app.config import settings
from app.tasks import ping

app = FastAPI(title="Plateforme IA - Marchés publics")
engine = create_engine(settings.database_url, pool_pre_ping=True)


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
        db_ok = conn.execute(text("SELECT 1")).scalar() == 1
    redis_ok = redis.from_url(settings.redis_url).ping()
    return {"db": db_ok, "redis": redis_ok}


@app.post("/debug/ping")
def debug_ping():
    """Vérifie que Celery + Redis fonctionnent (à supprimer plus tard)."""
    return {"result": ping.delay().get(timeout=5)}
