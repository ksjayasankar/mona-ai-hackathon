"""Test config: fully OFFLINE + FREE. Forces the local Ollama provider, a dev-auth
bypass, and a throwaway SQLite DB — so the suite never touches the Gemini quota or a
real database. (Vision would route to Gemini, so tests use TEXT documents only.)

The DB path is made UNIQUE per process and its sibling journal/WAL files are cleaned up.
A leftover `-wal`/`-shm`/`-journal` from a previously killed run, or a pooled connection
pinned to a since-recreated inode, otherwise surfaces intermittently as SQLite
"attempt to write a readonly database" once more than one test module writes to the DB.
"""
import os
import tempfile

os.environ["LLM_PROVIDER"] = "ollama"
os.environ["AUTH_MODE"] = "dev"
_DB = os.path.join(tempfile.gettempdir(), f"mona_test_{os.getpid()}.db")
for _suffix in ("", "-journal", "-wal", "-shm"):
    _f = _DB + _suffix
    if os.path.exists(_f):
        os.remove(_f)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"

import pytest  # noqa: E402

from core.db import engine, init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _db():
    # Drop any connection pooled at import time so every connection binds to the
    # freshly-created file (guards against SQLITE_READONLY_DBMOVED across modules).
    engine.dispose()
    init_db()
    yield
    engine.dispose()
    for _suffix in ("", "-journal", "-wal", "-shm"):
        _f = _DB + _suffix
        if os.path.exists(_f):
            try:
                os.remove(_f)
            except OSError:
                pass
