from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from sitegen.clients import openrouter
from sitegen.settings import settings
from tests.conftest import approved_company, core_company, make_company, make_site

CATALOG = [
    {"id": "openai/gpt-4o-mini", "name": "GPT-4o mini", "prompt": 0.00000015, "completion": 0.0000006},
    {"id": "anthropic/claude-haiku-5.5", "name": "Haiku", "prompt": 0.0000001, "completion": 0.0000005},
    {"id": "meta/llama-free", "name": "Llama", "prompt": 0.0, "completion": 0.0},
]


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openrouter, "list_models", lambda http=None: CATALOG)


def test_presets_have_prices_per_million(client: TestClient, catalog: None):
    body = client.get("/api/models").json()
    mini = next(m for m in body["presets"] if m["id"] == "openai/gpt-4o-mini")
    assert mini["prompt_per_m"] == pytest.approx(0.15)
    assert mini["completion_per_m"] == pytest.approx(0.6)
    assert mini["label"] == "GPT-4o mini"
    # не из готового списка идут в подсказки
    assert body["others"] == ["meta/llama-free"]


def test_presets_without_catalog(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(openrouter, "list_models", lambda http=None: [])
    body = client.get("/api/models").json()
    assert body["presets"]
    assert all(m["prompt_per_m"] is None for m in body["presets"])
    assert body["others"] == []


def test_models_from_settings_are_listed(client: TestClient, catalog: None, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "openrouter_models", "openai/gpt-4o-mini,acme/special")
    monkeypatch.setattr(settings, "default_model", "acme/default")
    ids = [m["id"] for m in client.get("/api/models").json()["presets"]]
    assert ids[0] == "acme/default"
    assert "acme/special" in ids
    assert ids.count("openai/gpt-4o-mini") == 1


def test_config_has_limit_presets(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "max_cost_usd", 0.2)
    body = client.get("/api/config").json()
    assert body["cost_presets"] == [0.05, 0.1, 0.2, 0.5, 1.0]
    assert body["max_cost_cap_usd"] == settings.max_cost_cap_usd


def test_limit_from_request_is_used(client: TestClient):
    job = client.post("/api/companies/generate", json={"aspects": [], "max_cost": 0.5}).json()
    assert job["limit"] == 0.5
    job = client.post("/api/companies/generate", json={"aspects": []}).json()
    assert job["limit"] == settings.max_cost_usd


@pytest.mark.parametrize("bad", [0, -1, 100])
def test_bad_limit_is_rejected(client: TestClient, bad: float):
    r = client.post("/api/companies/generate", json={"max_cost": bad})
    assert r.status_code == 400
    assert "Лимит" in r.json()["detail"]


def test_small_limit_stops_generation_early(client: TestClient):
    cid = core_company(client, aspects=["legal", "privacy"])
    client.post(f"/api/companies/{cid}/approve-facts")
    # хватает только на один раздел, второй пропускается
    job = client.post(f"/api/companies/{cid}/sections", json={"max_cost": 0.003}).json()
    assert job["status"] == "done"
    assert "лимит" in job["warning"]


def test_limit_for_section_and_site(client: TestClient):
    cid = make_company(client, aspects=[])
    job = client.post(f"/api/companies/{cid}/aspects/security", json={"max_cost": 1.0}).json()
    assert job["limit"] == 1.0
    assert client.post(f"/api/companies/{cid}/aspects/security", json={"max_cost": 0}).status_code == 400

    cid = approved_company(client)
    assert make_site(client, cid, max_cost=0.05)["limit"] == 0.05
    assert client.post("/api/sites", json={"company_id": cid, "language": "ru", "max_cost": 99}).status_code == 400


def test_custom_model_is_accepted(client: TestClient):
    job = client.post("/api/companies/generate", json={"aspects": [], "model": "acme/custom-model:free"}).json()
    assert job["status"] == "done"
    company = client.get(f"/api/companies/{job['result_id']}").json()
    assert company["model"] == "acme/custom-model:free"


# ---------- каталог OpenRouter ----------

def counting(body: Any, code: int = 200) -> tuple[httpx.Client, list[int]]:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(code, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_catalog_is_cached():
    http, calls = counting({"data": [{"id": "a/b", "pricing": {"prompt": "0.000001", "completion": "0.000002"}}]})
    first = openrouter.list_models(http)
    assert first == [{"id": "a/b", "name": "a/b", "prompt": 0.000001, "completion": 0.000002,
                      "image_output": 0.0, "makes_images": False}]
    assert openrouter.list_models(http) == first
    assert len(calls) == 1


def test_catalog_refreshes_after_ttl(monkeypatch: pytest.MonkeyPatch):
    http, calls = counting({"data": [{"id": "a/b", "pricing": {}}]})
    openrouter.list_models(http)
    monkeypatch.setattr(openrouter, "CATALOG_TTL", -1)
    openrouter.list_models(http)
    assert len(calls) == 2


def test_catalog_failure_keeps_old_list(monkeypatch: pytest.MonkeyPatch):
    good, _ = counting({"data": [{"id": "a/b", "pricing": {}}]})
    old = openrouter.list_models(good)
    monkeypatch.setattr(openrouter, "CATALOG_TTL", -1)
    bad, _ = counting({"error": "down"}, code=503)
    assert openrouter.list_models(bad) == old
    broken, _ = counting({"data": [{"нет id": 1}]})
    assert openrouter.list_models(broken) == old


def test_catalog_without_network_is_empty():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет сети")

    assert openrouter.list_models(httpx.Client(transport=httpx.MockTransport(down))) == []
