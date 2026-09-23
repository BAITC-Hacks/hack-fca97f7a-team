"""Never use paid model APIs from the automated test suite."""
import pytest


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
