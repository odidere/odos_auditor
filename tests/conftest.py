import pytest


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Each test gets default config, a fresh working dir and no real credentials."""
    from odos.config import reload_config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ODOS_CONFIG", str(tmp_path / "missing.yaml"))
    for var in ("DATABASE_URL", "POSTGRES_HOST", "OPENAI_API_KEY", "GEMINI_API_KEY", "ODOS_API_KEY",
                "ODOS_COST_SOURCE", "SNOWFLAKE_ACCOUNT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ODOS_DECISIONS_PATH", str(tmp_path / "decisions.jsonl"))
    reload_config()
    yield
    reload_config()


@pytest.fixture
def db_session():
    """In-memory SQLite session with the full Odos schema."""
    pytest.importorskip("sqlalchemy")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from odos.backend.models import Base

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


class FakeProvider:
    """Stands in for OpenAI/Gemini. Returns queued responses or raises queued errors."""

    def __init__(self, name="fake", responses=None, model="fake-1"):
        self.name = name
        self.model = model
        self.responses = list(responses or [])
        self.prompts = []

    def complete_json(self, system, prompt):
        self.prompts.append(prompt)
        item = self.responses.pop(0) if self.responses else RuntimeError("no response queued")
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def fake_provider_cls():
    return FakeProvider
