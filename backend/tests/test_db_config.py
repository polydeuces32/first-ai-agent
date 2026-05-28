from __future__ import annotations

import os

from app.main import ALLOWED_ORIGINS, SessionLocal, engine


def test_postgres_pool_defaults_present() -> None:
    assert SessionLocal.kw.get("expire_on_commit") is False
    assert engine.pool._pre_ping is True
    assert ALLOWED_ORIGINS


def test_env_pool_variables_documented() -> None:
    assert os.getenv("DB_POOL_SIZE", "5").isdigit()
    assert os.getenv("DB_MAX_OVERFLOW", "10").isdigit()
    assert os.getenv("DB_POOL_RECYCLE_SECONDS", "1800").isdigit()
    assert os.getenv("DB_POOL_TIMEOUT_SECONDS", "30").isdigit()
