"""Test config: fully OFFLINE + FREE. Forces the local Ollama provider, a dev-auth
bypass, and a throwaway SQLite DB — so the suite never touches the Gemini quota or a
real database. (Vision would route to Gemini, so tests use TEXT documents only.)"""
import os
import tempfile

os.environ["LLM_PROVIDER"] = "ollama"
os.environ["AUTH_MODE"] = "dev"
_DB = os.path.join(tempfile.gettempdir(), "mona_test.db")
if os.path.exists(_DB):
    os.remove(_DB)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"

import pytest  # noqa: E402

from core.db import init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _db():
    init_db()
    yield
