import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from sitegen.settings import settings
from tests.conftest import FakeLlm, approved_company, core_company, make_company


def test_config_has_no_secrets(client: TestClient):
    r = client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert body["has_key"] is True
    assert "sk-or-test-key" not in r.text
    assert body["catalog"]["countries"] == [{"key": "DE", "label": "Германия"}, {"key": "RU", "label": "Россия"}]
    assert {s["key"] for s in body["schemes"]} >= {"ocean", "graphite"}


def test_generate_creates_draft_company(client: TestClient, llm: FakeLlm):
    cid = core_company(client, brand="Zeta", scale="small", direction="investment_research")
    company = client.get(f"/api/companies/{cid}").json()
    assert company["brand"] == "Zeta"
    # этап 1: только общие факты, разделов ещё нет
    assert company["status"] == "draft"
    assert company["data"]["sections"] == {}
    assert company["state"]["planned"] == ["legal", "requisites", "privacy", "security", "references"]
    assert company["cost"] == pytest.approx(0.003)
    assert company["data"]["scale"] == "small"
    assert company["data"]["direction"] == "investment_research"
    assert company["params"]["resolved"]["city"] == company["data"]["contacts"]["city"]
    assert len(company["data"]["people"]) >= 5


def test_job_reports_stage_and_cost(client: TestClient):
    r = client.post("/api/companies/generate", json={})
    job = r.json()
    assert (job["status"], job["stage"]) == ("done", "Готово")
    assert job["cost_known"] is True
    assert job["limit"] == settings.max_cost_usd
    assert client.get(f"/api/jobs/{job['id']}").json()["result_id"] == job["result_id"]


def test_second_company_gets_list_of_existing(client: TestClient, llm: FakeLlm):
    make_company(client)
    first_brand = client.get("/api/companies").json()[0]["brand"]
    make_company(client)
    assert first_brand in llm.calls[1][-1]["content"]
    brands = [c["brand"] for c in client.get("/api/companies").json()]
    assert len(set(brands)) == 2


def test_generate_without_key(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr(""))
    r = client.post("/api/companies/generate", json={})
    assert r.status_code == 502
    assert "OPENROUTER_API_KEY" in r.json()["detail"]


def test_generate_bad_input(client: TestClient):
    assert client.post("/api/companies/generate", json={"direction": "nope"}).status_code == 400
    assert client.post("/api/companies/generate", json={"model": "без слэша"}).status_code == 400
    r = client.post("/api/companies/generate", json={"language": "fr"})
    assert r.status_code == 422
    assert "Язык" in r.json()["detail"]


def test_model_error_becomes_failed_job(client: TestClient, llm: FakeLlm):
    from sitegen.errors import LlmError

    llm.error = LlmError("Модель не дала корректный ответ")
    job = client.post("/api/companies/generate", json={}).json()
    assert job["status"] == "error"
    assert "корректный ответ" in job["error"]
    assert client.get("/api/companies").json() == []


def test_unexpected_error_hides_details(client: TestClient, llm: FakeLlm):
    llm.error = RuntimeError("секретная внутренняя деталь")
    job = client.post("/api/companies/generate", json={}).json()
    assert job["status"] == "error"
    assert "секретная" not in job["error"]


def test_list_and_get(client: TestClient):
    first, second = make_company(client), make_company(client)
    ids = [c["id"] for c in client.get("/api/companies").json()]
    assert ids == [second, first]
    assert client.get("/api/companies/999").status_code == 404


def test_edit_saves_and_resets_approval(client: TestClient):
    cid = approved_company(client)
    data = client.get(f"/api/companies/{cid}").json()["data"]
    data["tagline"] = "Новое предложение компании для клиентов"
    r = client.put(f"/api/companies/{cid}", json=data)
    assert r.status_code == 200
    assert r.json()["status"] == "draft"
    assert client.get(f"/api/companies/{cid}").json()["data"]["tagline"].startswith("Новое")


def test_edit_rejects_broken_card(client: TestClient):
    cid = make_company(client)
    data = client.get(f"/api/companies/{cid}").json()["data"]

    # кода 11 нет ни у одного города каталога
    data["contacts"]["phone"] = "+49 11 1234 5678"
    r = client.put(f"/api/companies/{cid}", json=data)
    assert r.status_code == 400
    assert "телефон" in r.json()["detail"]

    data["contacts"]["phone"] = "+49 30 1234 5678"
    data["faq"] = data["faq"][:3]
    r = client.put(f"/api/companies/{cid}", json=data)
    assert r.status_code == 400
    assert "faq" in r.json()["detail"]

    assert client.put("/api/companies/999", json=data).status_code == 404


def test_approve_and_download(client: TestClient):
    cid = make_company(client, brand="Zeta")
    assert client.post(f"/api/companies/{cid}/approve").json()["status"] == "approved"
    r = client.get(f"/api/companies/{cid}/download")
    assert r.headers["content-disposition"] == f'attachment; filename="company-{cid}-zeta.json"'
    assert r.json()["brand"] == "Zeta"
    assert "sk-or" not in r.text
    assert client.post("/api/companies/999/approve").status_code == 404


def test_companies_get_six_digit_codes(client: TestClient):
    from sitegen.core.companies import public_code

    codes = {public_code(i) for i in range(1, 5001)}
    assert len(codes) == 5000
    assert all(100000 <= c <= 999999 for c in codes)
    cid = make_company(client)
    body = client.get(f"/api/companies/{cid}").json()
    assert body["code"] == public_code(cid)
    assert client.get("/api/companies").json()[0]["code"] == body["code"]
