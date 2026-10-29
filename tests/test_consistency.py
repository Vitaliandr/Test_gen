import copy
from typing import Any

import pytest
from fastapi.testclient import TestClient

from sitegen.card import Company, CompanyContent
from sitegen.core import builder, consistency
from sitegen.core.text import slugify
from tests.conftest import example


def card_with(**changes: Any) -> Company:
    data = example("kapitalklar")
    for path, value in changes.items():
        node = data
        *head, last = path.split("__")
        for step in head:
            node = node[step]
        node[last] = value
    return Company.model_validate(data)


def test_examples_are_consistent():
    for name in ("kapitalklar", "datenpegel"):
        assert consistency.check_company(Company.model_validate(example(name))) == []


def test_phone_from_other_city():
    issues = consistency.check_company(card_with(contacts__phone="+49 89 4120 3856"))
    assert any("телефон" in i for i in issues)


def test_postcode_from_other_city():
    issues = consistency.check_company(card_with(contacts__postal_code="80331"))
    assert any("индекс" in i for i in issues)


def test_unknown_city_and_country():
    assert consistency.check_company(card_with(contacts__city="Paris"))
    assert consistency.check_company(card_with(country="FR"))


def test_email_domain_must_match_brand():
    assert any("домен" in i for i in consistency.check_company(card_with(contacts__email="info@other.de")))
    assert any("почта" in i for i in consistency.check_company(card_with(contacts__email="не почта")))


def test_template_leftovers_found():
    issues = consistency.check_company(card_with(tagline="Лучшие в {{ city }} аналитики"))
    assert any("шаблон" in i for i in issues)


def test_history_must_mention_founding_year():
    assert any("год основания" in i for i in consistency.check_company(card_with(founding_year=2020)))


def test_duplicate_people_and_levels():
    data = example("kapitalklar")
    data["people"][4]["name"] = data["people"][3]["name"]
    assert any("повторяются" in i for i in consistency.check_company(Company.model_validate(data)))

    data = example("kapitalklar")
    data["people"][1]["level"] = "ceo"
    with pytest.raises(ValueError, match="people"):
        Company.model_validate(data)


def test_faq_must_have_five_items():
    data = example("kapitalklar")
    data["faq"].pop()
    with pytest.raises(ValueError):
        CompanyContent.model_validate(data)


def test_existing_brand_and_legal_form():
    fields = CompanyContent.model_fields
    content = CompanyContent.model_validate({k: v for k, v in example("kapitalklar").items() if k in fields})
    assert any("уже есть" in i for i in consistency.check_content(content, existing_brands=["kapitalklar"]))
    assert any("форма" in i for i in consistency.check_content(content, legal_form="AG"))


def render(name: str = "kapitalklar") -> tuple[dict[str, Any], dict[str, bytes]]:
    data = example(name)
    return data, builder.render_site(data, data, data["language"], "ocean", "sans")


def pages_of(files: dict[str, bytes]) -> dict[str, str]:
    return {n: b.decode() for n, b in files.items() if n.endswith(".html")}


def test_good_site_passes_all_checks():
    data, files = render()
    report = consistency.check_site(data, data, pages_of(files), files, "ru")
    assert report["ok"], [c for c in report["checks"] if not c["ok"]]


def test_site_check_finds_missing_phone():
    data, files = render()
    pages = pages_of(files)
    pages["product.html"] = pages["product.html"].replace(data["contacts"]["phone"], "")
    report = consistency.check_site(data, data, pages, files, "ru")
    assert not report["ok"]
    assert any("product.html: телефон" in c["detail"] for c in report["checks"])


def test_site_check_finds_leftover_variable_and_missing_photo():
    data, files = render()
    pages = pages_of(files)
    pages["index.html"] += "<p>{{ brand }}</p>"
    files = {k: v for k, v in files.items() if k != "assets/team/p5.svg"}
    failed = {c["name"] for c in consistency.check_site(data, data, pages, files, "ru")["checks"] if not c["ok"]}
    assert "Нет незаменённых переменных и заглушек" in failed
    assert "У каждого сотрудника есть фото, не меньше пяти" in failed


def test_site_check_finds_missing_pages_and_meta():
    data, files = render()
    pages = pages_of(files)
    broken = copy.deepcopy(pages)
    del broken["company.html"]
    assert not consistency.check_site(data, data, broken, files, "ru")["ok"]
    pages["index.html"] = pages["index.html"].replace('rel="icon"', 'rel="x"')
    failed = {c["name"] for c in consistency.check_site(data, data, pages, files, "ru")["checks"] if not c["ok"]}
    assert "Заголовок, описание, favicon и язык на каждой странице" in failed


def test_slugify():
    assert slugify("Kapitalklar") == "kapitalklar"
    assert slugify("Größe & Söhne GmbH") == "groesse-soehne-gmbh"
    assert slugify("Капитал Ясно") == "kapital-yasno"
    assert slugify("???") == "firma"


@pytest.mark.parametrize(
    "text",
    [
        "Зарегистрируйтесь на нашем сайте и получите доступ к аналитике.",
        "Клиент загружает свои файлы в личном кабинете и видит результат.",
        "Оставьте заявку, и мы перезвоним в течение дня.",
        "Laden Sie Ihre Unterlagen hoch, die Auswertung startet sofort per Upload.",
    ],
)
def test_core_card_cannot_promise_site_features(text: str):
    issues = consistency.check_company(card_with(value_proposition=text))
    assert any("функции, которых нет на сайте" in i for i in issues), issues


@pytest.mark.parametrize(
    "text",
    [
        "Платформа не поддерживает загрузку пользовательских файлов и не имеет личного кабинета.",
        "Компания зарегистрирована в Москве и работает с фондами по договору.",
        "Wir analysieren, welche Unternehmen aktiv Patente anmelden und wie schnell.",
        "Система сама загружает отчёты эмитентов из открытых источников.",
    ],
)
def test_honest_texts_are_not_flagged(text: str):
    issues = consistency.check_company(card_with(value_proposition=text))
    assert not any("функции, которых нет на сайте" in i for i in issues), issues


def test_random_country_is_accepted(client: TestClient):
    job = client.post("/api/companies/generate", json={"country": "random", "aspects": []}).json()
    assert job["status"] == "done", job
    country = client.get(f"/api/companies/{job['result_id']}").json()["data"]["country"]
    assert country in ("DE", "RU")


@pytest.mark.parametrize(
    ("change", "path"),
    [
        (lambda d: d["advantages"].__setitem__(0, ""), "advantages[0]"),
        (lambda d: d["product"]["limitations"].__setitem__(1, "   "), "product.limitations[1]"),
        (lambda d: d.__setitem__("tagline", " " * 20), "tagline"),
    ],
)
def test_blank_fields_are_found(change: Any, path: str):
    data = example("kapitalklar")
    change(data)
    issues = consistency.check_company(Company.model_validate(data))
    assert any("пустые поля" in i and path in i for i in issues), issues


def test_blank_section_field_is_found():
    data = example("kapitalklar")
    data["sections"]["security"]["measures"][0]["area"] = "   "
    issues = consistency.check_company(Company.model_validate(data))
    assert any("Безопасность: пустые поля" in i for i in issues), issues


@pytest.mark.parametrize(
    "text",
    ["Лучшие аналитики в {city} для фондов", "Лучшие аналитики в [город] для фондов", "Работаем для <Бренд> давно",
     "Отчёт за %s дней готов", "Пишите на $email в любой день", "Пишите на ${email} в любой день"],
)
def test_more_template_leftovers(text: str):
    issues = consistency.check_company(card_with(tagline=text))
    assert any("шаблонный" in i for i in issues), issues


@pytest.mark.parametrize("text", ["Отчёт стоит от $500 в месяц для фонда", "Скидка 20% для новых клиентов фонда"])
def test_money_and_percent_are_not_leftovers(text: str):
    issues = consistency.check_company(card_with(tagline=text))
    assert not any("шаблонный" in i for i in issues), issues
