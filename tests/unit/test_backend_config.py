"""
Tests for backend/config.py's Settings.

Focused on the DATABASE_URL scheme normalization added for the Render
deployment (docs/DEPLOYMENT.md) — Render (and Heroku-style platforms
before it) hand out a Postgres connection string starting with the
legacy `postgres://` scheme, which SQLAlchemy 1.4+ rejects outright.
Without this fix, pasting Render's own connection string verbatim into
DATABASE_URL would crash at engine creation on first boot.
"""
from backend.config import Settings


class TestDatabaseUrlNormalization:
    def test_legacy_postgres_scheme_is_rewritten(self):
        s = Settings(DATABASE_URL="postgres://user:pass@host:5432/db")
        assert s.DATABASE_URL == "postgresql://user:pass@host:5432/db"

    def test_already_correct_scheme_is_left_alone(self):
        s = Settings(DATABASE_URL="postgresql://user:pass@host:5432/db")
        assert s.DATABASE_URL == "postgresql://user:pass@host:5432/db"

    def test_sqlite_url_is_left_alone(self):
        s = Settings(DATABASE_URL="sqlite:///./netraksh.db")
        assert s.DATABASE_URL == "sqlite:///./netraksh.db"
