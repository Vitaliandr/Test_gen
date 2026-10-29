import copy
import random
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sitegen import catalog
from sitegen.aspects import registry
from sitegen.aspects.base import Ctx
from sitegen.card import Company
from sitegen.core import builder, consistency, generator, photos
from tests.conftest import FakeLlm, ru_card


def issues(change: Any = None) -> list[str]:
    data = ru_card()
    if change:
        change(data)
    return consistency.check_company(Company.model_validate(data))


def test_russian_card_passes_all_checks():
    assert issues() == []


def test_russian_contacts():
    rng = random.Random(3)
    r = generator.resolve_params({"country": "RU"}, rng)
    c = generator.make_contacts(r, "Сорвейн", rng)
    assert c.phone.startswith("+7 ")
    assert len(c.postal_code) == 6
    assert ", д. " in c.street
    assert c.email == "info@sorveyn.ru"
    assert r["legal_form"] in ("ООО", "АО")


def test_russian_postcode_and_phone_rules():
    assert any("индекс" in i for i in issues(lambda d: d["contacts"].update(postal_code="10100")))
    assert any("телефон" in i for i in issues(lambda d: d["contacts"].update(phone="+7 812 123 4567")))
    assert any("домен" in i for i in issues(lambda d: d["contacts"].update(email="info@kapitalklar.de")))


def test_other_russian_city_in_history():
    def change(d: dict[str, Any]) -> None:
        d["history"] = d["history"].replace("в Москве", "в Казани")

    assert any("Казань" in i for i in issues(change))


def test_russian_terms_need_russian_law():
    legal = ru_card()["sections"]["legal"]

    def change(d: dict[str, Any]) -> None:
        for term in d["sections"]["legal"]["terms"]:
            term["text"] = term["text"].replace("Российской Федерации", "Германии")

    assert legal
    assert any("применимое право" in i for i in issues(change))


@pytest.mark.parametrize(
    ("what", "change"),
    [
        ("152-ФЗ", lambda p: [i.update(legal_basis="законный интерес") for i in p["data_processed"]]),
        ("Роскомнадзор", lambda p: p.update(rights=[r.replace("Роскомнадзоре", "суде") for r in p["rights"]])),
        ("Трансграничная", lambda p: p.update(sections=[s for s in p["sections"] if "Трансграничн" not in s["title"]])),
        ("действия", lambda p: [i.update(actions="") for i in p["data_processed"]]),
        ("территории", lambda p: p.update(sections=[
            dict(s, text="Данные хранятся у оператора и уничтожаются по достижении цели обработки персональных данных.")
            if "хранени" in s["title"] else s for s in p["sections"]])),
    ],
)
def test_russian_privacy_rules(what: str, change: Any):
    def apply(d: dict[str, Any]) -> None:
        change(d["sections"]["privacy"])

    found = issues(apply)
    assert any(what in i for i in found), found


def test_german_privacy_does_not_need_russian_sections():
    from tests.conftest import example

    data = example("kapitalklar")
    assert data["sections"]["privacy"].get("sections", []) == []
    assert consistency.check_company(Company.model_validate(data)) == []


def test_prompts_follow_the_country():
    data = ru_card()
    ctx = Ctx.from_card(data)
    legal = registry.get("legal").prompt(ctx)
    assert "право Российской Федерации" in legal
    assert "претензионный" in legal
    assert "Impressum" not in legal
    privacy = registry.get("privacy").prompt(ctx)
    assert "152-ФЗ" in privacy
    assert "Трансграничная передача персональных данных" in privacy
    assert "Russia" in photos.prompt_for(data["people"][0], data)


def test_russian_site_pages():
    data = ru_card()
    files = builder.render_site(data, data, "ru", "ocean", "sans")
    legal = files["legal.html"].decode()
    privacy = files["privacy.html"].decode()
    assert "Сведения о компании" in legal
    assert "Impressum" not in legal
    assert "Трансграничная передача персональных данных" in privacy
    assert "сбор, запись, хранение, уничтожение" in privacy
    assert "Россия" in files["company.html"].decode()
    pages = {n: b.decode() for n, b in files.items() if n.endswith(".html")}
    report = consistency.check_site(data, data, pages, files, "ru")
    assert report["ok"], [c for c in report["checks"] if not c["ok"]]


def test_generate_russian_company(client: TestClient, llm: FakeLlm):
    r = client.post("/api/companies/generate", json={"country": "RU", "aspects": []})
    job = r.json()
    assert job["status"] == "done", job
    company = client.get(f"/api/companies/{job['result_id']}").json()
    assert company["data"]["country"] == "RU"
    assert company["data"]["contacts"]["city"] in catalog.COUNTRIES["RU"]["cities"]
    assert company["data"]["contacts"]["phone"].startswith("+7 ")
    assert company["issues"] == []
    assert "русские" in llm.calls[0][-1]["content"]


def test_unknown_country_is_rejected(client: TestClient):
    assert client.post("/api/companies/generate", json={"country": "FR"}).status_code == 400


def test_russian_card_translates_to_german():
    from sitegen.clients.openrouter import Budget
    from sitegen.core import translate

    out = translate.translate_card(ru_card(), "de", "m/m", FakeLlm(), Budget(1), lambda s: None)
    assert out["contacts"] == ru_card()["contacts"]
    files = builder.render_site(ru_card(), out, "de", "ocean", "sans")
    assert "Angaben zum Unternehmen" in files["legal.html"].decode()
    assert "Russland" in files["company.html"].decode()
    assert copy.deepcopy(out)["language"] == "de"


@pytest.mark.parametrize(
    ("country", "lang", "phrase"),
    [
        ("RU", "ru", "не является публичной офертой"),
        ("RU", "de", "kein öffentliches Angebot"),
        ("DE", "ru", "не являются обязывающим предложением"),
        ("DE", "de", "kein verbindliches Angebot"),
    ],
)
def test_offer_note_in_every_footer(country: str, lang: str, phrase: str):
    from tests.conftest import example

    data = ru_card() if country == "RU" else example("kapitalklar")
    for theme in builder.THEMES:
        files = builder.render_site(data, data, lang, "ocean", "sans", theme)
        pages = [n for n in files if n.endswith(".html")]
        assert all(phrase in files[n].decode() for n in pages), theme


def test_offer_note_is_checked():
    data = ru_card()
    files = builder.render_site(data, data, "ru", "ocean", "sans")
    cut = "не является публичной офертой"
    pages = {n: b.decode().replace(cut, "") for n, b in files.items() if n.endswith(".html")}
    report = consistency.check_site(data, data, pages, files, "ru")
    assert not report["ok"]
    assert any("оферт" in c["name"] and not c["ok"] for c in report["checks"])


def test_security_page_has_no_claims_block():
    data = ru_card()
    page = builder.render_site(data, data, "ru", "ocean", "sans")["security.html"].decode()
    assert "Что мы не заявляем" not in page


@pytest.mark.parametrize(("lang", "phrase"), [("ru", "Сайт создан для демонстрации"), ("de", "nur zur Demonstration")])
def test_demo_note_in_every_footer(lang: str, phrase: str):
    data = ru_card()
    for theme in builder.THEMES:
        files = builder.render_site(data, data, lang, "ocean", "sans", theme)
        pages = [n for n in files if n.endswith(".html")]
        assert all(phrase in files[n].decode() for n in pages), theme


def test_demo_note_is_checked():
    data = ru_card()
    files = builder.render_site(data, data, "ru", "ocean", "sans")
    cut = builder.STRINGS["ru"]["demo_note"]
    pages = {n: b.decode().replace(cut, "") for n, b in files.items() if n.endswith(".html")}
    report = consistency.check_site(data, data, pages, files, "ru")
    assert any("демонстрационных" in c["name"] and not c["ok"] for c in report["checks"])
