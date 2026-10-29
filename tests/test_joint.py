import copy
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from sitegen import main
from sitegen.aspects.base import Ctx, facts_block
from sitegen.card import Company
from sitegen.core import consistency, review
from sitegen.settings import settings
from tests.conftest import FakeLlm, approved_company, core_company, example, make_company, make_site, run_job


def issues(change: Any) -> list[str]:
    data = example("kapitalklar")
    change(data)
    return consistency.check_company(Company.model_validate(data))


# ---------- общие факты сверяются кодом ----------

def test_employee_count_in_texts_must_match():
    found = issues(lambda d: d.update(employee_count=40))
    assert any("18 сотрудников, а по фактам 40" in i for i in found)


def test_founding_year_in_texts_must_match():
    def change(d: dict[str, Any]) -> None:
        d["people"][0]["bio"] += " Основал компанию в 2019 году."

    assert any("основание в 2019" in i for i in issues(change))


def test_other_city_in_history_is_caught():
    def change(d: dict[str, Any]) -> None:
        d["history"] = d["history"].replace("в Берлине", "в Мюнхене")

    assert any("München" in i for i in issues(change))


def test_client_city_is_not_a_contradiction():
    # у клиентов свои города, это не факт о компании
    assert issues(lambda d: None) == []
    assert "Гамбург" in str(example("kapitalklar")["sections"]["references"])


def test_product_name_in_terms_must_be_current():
    found = issues(lambda d: d["product"].update(name="Klar Reports"))
    assert any("Klar Reports" in i for i in found)


# ---------- что видит модель ----------

def test_sections_see_all_facts_and_ready_sections():
    data = example("kapitalklar")
    block = facts_block(Ctx.from_card(data))
    for part in (data["history"], data["specialization"], data["audience"], data["faq"][0]["question"]):
        assert part in block
    assert data["product"]["process"][0] in block
    assert data["product"]["scenarios"][0]["title"] in block
    # готовые разделы тоже видны, кратко
    assert "Уже готовые разделы" in block
    assert "legal:" in block
    no_sections = {**data, "sections": {}}
    assert "Уже готовые разделы" not in facts_block(Ctx.from_card(no_sections))


# ---------- этапы утверждения ----------

def test_sections_need_approved_facts(client: TestClient):
    cid = core_company(client)
    job = run_job(client, f"/api/companies/{cid}/sections")
    assert job["status"] == "error"
    assert "утвердите общие факты" in job["error"]
    job = client.post(f"/api/companies/{cid}/aspects/legal", json={}).json()
    assert job["status"] == "error"


def test_facts_with_problems_cannot_be_approved(client: TestClient):
    cid = core_company(client, aspects=[])
    from sitegen.database import SessionLocal
    from sitegen.tables import Company as Row

    with SessionLocal() as session:
        row = session.get(Row, cid)
        assert row
        data = copy.deepcopy(row.data)
        data["employee_count"] = data["employee_count"] + 7
        row.data = data
        session.commit()
    r = client.post(f"/api/companies/{cid}/approve-facts")
    assert r.status_code == 400
    assert "сотрудников" in r.json()["detail"]


def test_full_flow_and_statuses(client: TestClient, llm: FakeLlm):
    cid = core_company(client)
    assert client.get(f"/api/companies/{cid}").json()["status"] == "draft"

    r = client.post(f"/api/companies/{cid}/approve-facts")
    assert r.json()["status"] == "facts_approved"
    assert r.json()["state"]["facts_approved"] is True

    job = run_job(client, f"/api/companies/{cid}/sections")
    assert job["status"] == "done"
    assert job["warning"] is None
    company = client.get(f"/api/companies/{cid}").json()
    assert set(company["data"]["sections"]) == {"legal", "requisites", "privacy", "security", "references"}
    assert company["state"]["review_current"] is True
    assert company["state"]["review"]["ok"] is True
    assert company["state"]["stale_sections"] == []
    assert len(llm.reviews) == 1

    assert client.post(f"/api/companies/{cid}/approve").json()["status"] == "approved"


def test_approve_needs_review(client: TestClient):
    cid = core_company(client, aspects=[])
    client.post(f"/api/companies/{cid}/approve-facts")
    r = client.post(f"/api/companies/{cid}/approve")
    assert r.status_code == 400
    assert "совместную проверку" in r.json()["detail"]
    assert client.post(f"/api/companies/{cid}/approve").status_code == 400


def test_approve_needs_facts(client: TestClient):
    cid = core_company(client, aspects=[])
    r = client.post(f"/api/companies/{cid}/approve")
    assert r.status_code == 400
    assert "общие факты" in r.json()["detail"]


def test_contradictions_block_approval(client: TestClient, llm: FakeLlm):
    found = {"where": "faq[1] и sections.legal.terms[1]", "problem": "2 дня и 10 дней", "fix": "привести к 2"}
    llm.contradictions = [found]
    cid = make_company(client)
    company = client.get(f"/api/companies/{cid}").json()
    assert company["state"]["review"]["ok"] is False
    assert company["state"]["review"]["contradictions"][0]["problem"] == "2 дня и 10 дней"
    r = client.post(f"/api/companies/{cid}/approve")
    assert r.status_code == 400
    assert "противоречия" in r.json()["detail"]

    # исправили, проверили заново, теперь можно
    llm.contradictions = []
    assert run_job(client, f"/api/companies/{cid}/review")["status"] == "done"
    assert client.post(f"/api/companies/{cid}/approve").status_code == 200


def test_editing_facts_drops_approval_and_marks_sections(client: TestClient):
    cid = approved_company(client)
    data = client.get(f"/api/companies/{cid}").json()["data"]
    data["tagline"] = "Новое предложение компании для клиентов"
    saved = client.put(f"/api/companies/{cid}", json=data).json()
    assert saved["status"] == "draft"
    assert saved["state"]["facts_approved"] is False
    assert saved["state"]["review_current"] is False

    #факты утвердили заново, а разделы уже по старым
    st = client.post(f"/api/companies/{cid}/approve-facts").json()["state"]
    assert set(st["stale_sections"]) == {"legal", "requisites", "privacy", "security", "references"}
    assert client.post(f"/api/companies/{cid}/approve").status_code == 400


def test_editing_section_keeps_facts_approved(client: TestClient):
    cid = approved_company(client)
    data = client.get(f"/api/companies/{cid}").json()["data"]
    data["sections"]["security"]["summary"] += " Подробности по запросу."
    saved = client.put(f"/api/companies/{cid}", json=data).json()
    assert saved["status"] == "facts_approved"
    assert saved["state"]["review_current"] is False
    assert saved["state"]["stale_sections"] == []


def test_site_needs_whole_flow(client: TestClient):
    cid = core_company(client, aspects=[])
    client.post(f"/api/companies/{cid}/approve-facts")
    job = make_site(client, cid)
    assert job["status"] == "error"


# ---------- совместная проверка моделью ----------

def test_code_problems_stop_review_before_paying(client: TestClient, llm: FakeLlm):
    cid = make_company(client)
    from sitegen.database import SessionLocal
    from sitegen.tables import Company as Row

    with SessionLocal() as session:
        row = session.get(Row, cid)
        assert row
        data = copy.deepcopy(row.data)
        data["sections"]["legal"]["imprint"]["represented_by"] = "Кто-то другой"
        row.data = data
        session.commit()
    calls = len(llm.reviews)
    job = run_job(client, f"/api/companies/{cid}/review")
    assert job["status"] == "error"
    assert "Сначала исправьте" in job["error"]
    assert len(llm.reviews) == calls


def test_review_prompt_has_whole_card_but_not_contacts():
    data = example("kapitalklar")
    prompt = review.build_prompt(data)[1]["content"]
    assert data["sections"]["legal"]["terms"][1]["text"] in prompt
    assert data["faq"][1]["answer"] in prompt
    assert data["contacts"]["phone"] not in prompt


def test_review_result_is_bound_to_card():
    data = example("kapitalklar")
    llm = FakeLlm()
    from sitegen.clients.openrouter import Budget

    result = review.review_card(data, "m/m", llm, Budget(1))
    assert result["ok"] is True
    changed = {**data, "tagline": "Другое предложение компании"}
    assert review.review_card(changed, "m/m", llm, Budget(1))["fp"] != result["fp"]


def test_review_limit_and_model(client: TestClient, llm: FakeLlm):
    cid = make_company(client)
    job = run_job(client, f"/api/companies/{cid}/review", model="acme/reviewer", max_cost=0.5)
    assert job["limit"] == 0.5
    assert client.get(f"/api/companies/{cid}").json()["state"]["review"]["model"] == "acme/reviewer"
    assert client.post(f"/api/companies/{cid}/review", json={"max_cost": 0}).status_code == 400


# ---------- перевод ----------

def test_translation_with_return_promise_is_rejected(client: TestClient, llm: FakeLlm):
    cid = approved_company(client)
    llm.translation_extra = {
        "sections/references/clients/0/description": "Wir garantieren Rendite für alle Kunden, jedes Jahr wieder."
    }
    job = make_site(client, cid, language="de")
    assert job["status"] == "error"
    assert "Перевод не прошёл проверку" in job["error"]
    assert "доходности" in job["error"]


def test_translation_that_moves_city_is_rejected(client: TestClient, llm: FakeLlm):
    cid = approved_company(client)
    data = client.get(f"/api/companies/{cid}").json()["data"]
    other = "Hamburg" if data["contacts"]["city"] != "Hamburg" else "Leipzig"
    # остальное как обычно, ловим именно город
    history = "[de] " + data["history"] + f" Ein zweites Büro gibt es in {other}."
    llm.translation_extra = {"history": history}
    job = make_site(client, cid, language="de")
    assert job["status"] == "error"
    assert other in job["error"]


# ---------- миграция ----------

def test_migration_adds_meta(tmp_path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite:///{tmp_path}/m.db"
    monkeypatch.setattr(settings, "database_url", url)
    main.run_migrations()
    engine = create_engine(url)
    columns = {c["name"] for c in inspect(engine).get_columns("companies")}
    engine.dispose()
    assert "meta" in columns


def test_old_stored_status_is_not_trusted(client: TestClient):
    #компания из старой версии, approved есть, а отпечатков нет
    cid = core_company(client, aspects=[])
    from sitegen.database import SessionLocal
    from sitegen.tables import Company as Row

    with SessionLocal() as session:
        row = session.get(Row, cid)
        assert row
        row.status = "approved"
        session.commit()
    assert client.get(f"/api/companies/{cid}").json()["status"] == "draft"
    assert client.get("/api/companies").json()[0]["status"] == "draft"
    assert make_site(client, cid)["status"] == "error"


def test_stale_sections_block_approval_until_rebuilt(client: TestClient, llm: FakeLlm):
    cid = approved_company(client)
    data = client.get(f"/api/companies/{cid}").json()["data"]
    data["tagline"] = "Новое предложение компании для клиентов"
    client.put(f"/api/companies/{cid}", json=data)
    client.post(f"/api/companies/{cid}/approve-facts")
    #проверка чистая, но разделы старые
    assert run_job(client, f"/api/companies/{cid}/review")["status"] == "done"
    r = client.post(f"/api/companies/{cid}/approve")
    assert r.status_code == 400
    assert "по старым фактам" in r.json()["detail"]

    # общая кнопка пересоздаёт и старые
    assert run_job(client, f"/api/companies/{cid}/sections")["status"] == "done"
    assert client.get(f"/api/companies/{cid}").json()["state"]["stale_sections"] == []
    assert run_job(client, f"/api/companies/{cid}/review")["status"] == "done"
    assert client.post(f"/api/companies/{cid}/approve").status_code == 200
