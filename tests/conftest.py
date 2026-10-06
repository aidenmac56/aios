import pytest

from aios.bootstrap import init
from aios.llm.provider import ProviderRegistry
from aios.llm.testing import ScriptedProvider
from aios.orchestrator.engine import Engine
from tests.fakes import responder


@pytest.fixture
def sm(tmp_path, monkeypatch):
    monkeypatch.setenv("AIOS_WEB_SEARCH", "1")
    return init(f"sqlite:///{tmp_path / 'test.db'}")


@pytest.fixture
def provider():
    return ScriptedProvider(responder())


@pytest.fixture
def engine(sm, provider):
    return Engine(sm, ProviderRegistry(providers={"anthropic": provider}, default="anthropic"))
