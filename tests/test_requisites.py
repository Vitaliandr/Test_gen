import copy
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from sitegen.aspects import registry
from sitegen.aspects.base import Ctx
from sitegen.aspects.requisites import checksum_ok
from sitegen.card import Company
from sitegen.core import builder, consistency
from sitegen.settings import settings
from tests.conftest import FakeLlm, core_company, example, ru_card

ASPECT = registry.get("requisites")


def values(data: dict[str, Any]) -> dict[str, str]:
    return {e["key"]: e["value"] for e in data["sections"]["requisites"]["entries"]}


def issues(data: dict[str, Any]) -> list[str]:
    return consistency.check_company(Company.model_validate(data))


def test_real_numbers_have_valid_checksums():
    # настоящие номера сбера, у них цифры сходятся
    assert checksum_ok("inn", "7707083893")
    assert checksum_ok("ogrn", "1027700132195")
    assert checksum_ok("vat_id", "DE136695976")


@pytest.mark.parametrize("data", [example("kapitalklar"), example("datenpegel"), ru_card()])
def test_built_requisites_pass_and_never_match_real_ones(data: dict[str, Any]):
    v = values(data)
    assert issues(data) == []
    for key in ("inn", "ogrn", "vat_id"):
        if key in v:
            assert not checksum_ok(key, v[key])


def test_same_company_gets_same_numbers():
    data = example("kapitalklar")
    assert ASPECT.build(Ctx.from_card(data)) == ASPECT.build(Ctx.from_card(data))


def test_russian_numbers_follow_facts():
    v = values(ru_card())
    assert v["inn"].startswith("77") and v["kpp"].startswith(v["inn"][:4])
    assert v["ogrn"][1:3] == "22"  # год основания 2022
    assert v["okved"] == "63.11"


@pytest.mark.parametrize(
    ("change", "text"),
    [
        (lambda v: v.update(ogrn="1" + "19" + v["ogrn"][3:]), "год в ОГРН"),
        (lambda v: v.update(inn="78" + v["inn"][2:]), "inn не из региона"),
        (lambda v: v.update(capital="5 000 ₽"), "меньше минимума"),
        (lambda v: v.update(director="Иван Иванов"), "руководитель"),
        (lambda v: v.update(inn="7707083893"), "может совпасть с реальной"),
        (lambda v: v.update(kpp="12345"), "не в формате"),
    ],
)
def test_russian_requisites_are_checked(change: Any, text: str):
    data = ru_card()
    v = values(data)
    change(v)
    data["sections"]["requisites"]["entries"] = [{"key": k, "value": x} for k, x in v.items()]
    assert any(text in i for i in issues(data)), issues(data)


def test_german_court_follows_city():
    data = example("kapitalklar")
    v = values(data)
    v["court"] = "Amtsgericht München"
    data["sections"]["requisites"]["entries"] = [{"key": k, "value": x} for k, x in v.items()]
    assert any("регистрационный суд" in i for i in issues(data))


def test_wrong_set_of_requisites():
    data = copy.deepcopy(ru_card())
    data["sections"]["requisites"] = example("kapitalklar")["sections"]["requisites"]
    assert any("для страны RU нужны" in i for i in issues(data))


def test_requisites_page():
    data = ru_card()
    files = builder.render_site(data, data, "de", "ocean", "sans")
    page = files["requisites.html"].decode()
    for value in values(data).values():
        assert value in page
    assert "OGRN" in page and data["legal_name"] in page
    pages = {n: b.decode() for n, b in files.items() if n.endswith(".html")}
    assert 'href="requisites.html"' in pages["index.html"]
    report = consistency.check_site(data, data, pages, files, "de")
    assert report["ok"], [c for c in report["checks"] if not c["ok"]]


def test_requisites_cost_nothing_and_need_no_key(client: TestClient, llm: FakeLlm, monkeypatch: pytest.MonkeyPatch):
    cid = core_company(client, aspects=[])
    client.post(f"/api/companies/{cid}/approve-facts")
    calls = len(llm.calls)
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "use_keyring", False)
    job = client.post(f"/api/companies/{cid}/aspects/requisites", json={}).json()
    assert job["status"] == "done", job
    assert job["cost"] == 0
    assert len(llm.calls) == calls
    company = client.get(f"/api/companies/{cid}").json()
    assert "requisites" in company["data"]["sections"]
    assert company["issues"] == []
