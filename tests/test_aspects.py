import copy
import json
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jinja2 import ChoiceLoader, DictLoader
from pydantic import BaseModel, Field

from scripts.export_schema import build_schema
from sitegen.aspects import registry
from sitegen.aspects.base import Aspect, Ctx, Page, result
from sitegen.card import Company
from sitegen.core import builder, consistency
from sitegen.core.text import norm
from sitegen.database import SessionLocal
from sitegen.errors import AppError
from sitegen.tables import Company as CompanyRow
from tests.conftest import FakeLlm, approved_company, core_company, example, make_company, make_site, run_job


def issues_with(**changes: Any) -> list[str]:
    #правим разделы примера и смотрим замечания
    data = example("kapitalklar")
    for path, value in changes.items():
        node: Any = data["sections"]
        *head, last = path.split("__")
        for step in head:
            node = node[int(step)] if step.isdigit() else node[step]
        node[int(last) if last.isdigit() else last] = value
    return consistency.check_company(Company.model_validate(data))


def test_five_aspects_are_registered():
    numbers = {a.key: a.number for a in registry.all_aspects()}
    assert numbers == {"legal": 2, "requisites": 3, "privacy": 6, "security": 7, "references": 8}


def test_unknown_aspect():
    with pytest.raises(AppError, match="Неизвестный раздел"):
        registry.get("nope")
    data = example("kapitalklar")
    data["sections"]["nope"] = {}
    with pytest.raises(ValueError, match="неизвестный раздел"):
        Company.model_validate(data)


def test_pages_follow_sections():
    core_only = [p.file for p in registry.pages_for([])]
    assert core_only == ["index.html", "product.html", "company.html"]
    every = [p.file for p in registry.pages_for(["legal", "requisites", "privacy", "security", "references"])]
    #security и references до контактов, юр. в подвале
    assert every == [
        "index.html", "product.html", "security.html", "references.html", "company.html", "legal.html",
        "requisites.html", "privacy.html",
    ]  # fmt: skip


def test_examples_pass_all_checks():
    assert issues_with() == []


# ---------- юридические документы ----------

def test_legal_checks():
    assert any("директор" in i for i in issues_with(legal__imprint__represented_by="Мария Брандт"))
    assert any("из команды" in i for i in issues_with(legal__imprint__content_responsible="Иван Посторонний"))
    legal = example("kapitalklar")["sections"]["legal"]
    nameless = {"legal__terms_intro": legal["terms_intro"].replace("Kapitalklar Analytics GmbH", "компания")}
    for i, term in enumerate(legal["terms"]):
        nameless[f"legal__terms__{i}__text"] = term["text"].replace("Kapitalklar Analytics GmbH", "компания")
    assert any("юридического названия" in i for i in issues_with(**nameless))
    registry_note = "Компания зарегистрирована, HRB 123456, содержание сайта проверено тщательно."
    assert any("номера из реестров" in i for i in issues_with(legal__imprint__liability_note=registry_note))
    assert any("год начала" in i for i in issues_with(legal__effective_year=2001))
    portal_note = "Споры решаются через личный кабинет клиента, а также по почте, если это удобнее."
    assert any("функции" in i for i in issues_with(legal__imprint__dispute_note=portal_note))


def test_legal_needs_governing_law_of_the_country():
    terms = example("kapitalklar")["sections"]["legal"]["terms"]
    texts = {f"legal__terms__{i}__text": t["text"].replace("Германия", "Страна") for i, t in enumerate(terms)}
    assert any("применимое право" in i for i in issues_with(**texts))


# ---------- персональные данные ----------

def test_privacy_checks():
    items = copy.deepcopy(example("kapitalklar")["sections"]["privacy"]["data_processed"])
    for item in items:
        item["legal_basis"] = "Согласие пользователя"
    assert any("GDPR" in i for i in issues_with(privacy__data_processed=items))

    items = copy.deepcopy(example("kapitalklar")["sections"]["privacy"]["data_processed"])
    items[0]["purpose"] = "Отправка новостной рассылки подписчикам сайта по их адресу почты."
    assert any("чего на сайте нет" in i for i in issues_with(privacy__data_processed=items))

    cookies = "Мы используем Google Analytics для подсчёта посетителей сайта."
    assert any("аналитики" in i for i in issues_with(privacy__cookies_statement=cookies))
    note = "Ответственный за обработку указан в подвале этого сайта."
    assert any("оператор" in i for i in issues_with(privacy__controller_note=note))


# ---------- безопасность ----------

def test_security_checks():
    cert = "Мы сертифицированы по ISO 27001 и регулярно проходим независимый аудит."
    assert any("сертификаты" in i for i in issues_with(security__summary=cert))
    absolute = "У нас абсолютная безопасность данных клиентов, взлом невозможен технически."
    assert any("абсолютные" in i for i in issues_with(security__summary=absolute))
    portal = "Клиент входит в личный кабинет, где видит все свои данные и может их удалить самостоятельно."
    assert any("функции" in i for i in issues_with(security__data_handling=portal))


# ---------- клиенты, отзывы, кейсы ----------

def test_references_checks():
    assert any("нет в списке" in i for i in issues_with(references__testimonials__0__client="Неизвестный клиент"))
    assert any("нет в списке" in i for i in issues_with(references__cases__0__client="Неизвестный клиент"))
    assert any("сотрудником" in i for i in issues_with(references__testimonials__0__author_name="Ларс Венцель"))
    assert any("вне диапазона" in i for i in issues_with(references__clients__0__since_year=2010))
    assert any("не из команды" in i for i in issues_with(references__publications__0__author="Иван Посторонний"))
    assert any("повторяются" in i for i in issues_with(references__clients__1__name="Nordlicht Family Office"))
    assert any("сама компания" in i for i in issues_with(references__clients__3__name="Kapitalklar"))


def test_no_made_up_links_and_no_return_promises():
    summary = "Подробности на https://example.com/report и в нашем блоге для всех клиентов компании."
    assert any("ссылки" in i for i in issues_with(references__publications__0__summary=summary))
    promise = "Мы гарантируем доходность выше рынка всем клиентам, которые подключатся к нашему сервису."
    assert any("доходности" in i for i in issues_with(references__clients__0__description=promise))


# ---------- генерация разделов через API ----------

def test_generate_makes_all_sections_by_default(client: TestClient, llm: FakeLlm):
    cid = make_company(client)
    data = client.get(f"/api/companies/{cid}").json()["data"]
    assert set(data["sections"]) == {"legal", "requisites", "privacy", "security", "references"}
    assert len(data["product"]["scenarios"]) >= 3
    # карточка, разделы и проверка
    assert len(llm.calls) == 6
    assert client.get(f"/api/companies/{cid}").json()["issues"] == []


def test_sections_can_be_chosen(client: TestClient, llm: FakeLlm):
    core = client.get(f"/api/companies/{make_company(client, aspects=[])}").json()["data"]
    assert core["sections"] == {}
    only = client.get(f"/api/companies/{make_company(client, aspects=['security'])}").json()["data"]
    assert list(only["sections"]) == ["security"]
    assert client.post("/api/companies/generate", json={"aspects": ["nope"]}).status_code == 400


def test_section_prompt_has_facts_and_rules(client: TestClient, llm: FakeLlm):
    make_company(client, brand="Zeta", aspects=["references"])
    prompt = next(c[-1]["content"] for c in llm.calls if c[-1]["content"].startswith("РАЗДЕЛ: references"))
    assert "бренд: Zeta" in prompt
    assert "вымышлено" in prompt
    assert "без обещаний" in prompt
    assert "Утверждённые факты" in prompt


def test_stage_names_include_sections(client: TestClient):
    job = client.post("/api/companies/generate", json={"aspects": ["security"]}).json()
    assert job["status"] == "done"


def test_bad_section_from_model_is_rejected(client: TestClient, llm: FakeLlm):
    bad = copy.deepcopy(example("kapitalklar")["sections"]["security"])
    bad["summary"] = "Мы сертифицированы по ISO 27001 и гордимся этим результатом много лет подряд."
    llm.custom["security"] = bad
    cid = core_company(client, aspects=["security", "legal"])
    client.post(f"/api/companies/{cid}/approve-facts")
    job = run_job(client, f"/api/companies/{cid}/sections")
    #удачные сохранились, про упавший пишем warning
    assert job["status"] == "done"
    assert "Безопасность" in job["warning"]
    assert "сертификаты" in job["warning"]
    company = client.get(f"/api/companies/{cid}").json()
    assert list(company["data"]["sections"]) == ["legal"]
    assert company["state"]["review"] is None
    # заплачено за карточку и оба раздела, неудачный тоже
    assert company["cost"] == pytest.approx(0.009)


def test_negated_statements_pass_checks():
    sec = "Мы не сертифицированы по ISO 27001. Абсолютной безопасности не бывает, поэтому описываем конкретные меры."
    assert issues_with(security__summary=sec) == []
    cookies = "Сайт не использует cookie, Google Analytics и другие инструменты аналитики."
    assert issues_with(privacy__cookies_statement=cookies) == []
    note = "Личного кабинета у клиентов нет, все материалы приходят по почте в виде заметок."
    assert issues_with(security__data_handling=note) == []
    promise = "Мы не гарантируем доходность и прямо пишем об этом в каждом договоре с клиентом."
    assert issues_with(references__clients__0__description=promise) == []


def _legal_for(row: CompanyRow) -> dict[str, Any]:
    text = json.dumps(example("kapitalklar")["sections"]["legal"], ensure_ascii=False)
    legal: dict[str, Any] = json.loads(text.replace("Kapitalklar Analytics GmbH", row.data["legal_name"]))
    legal["effective_year"] = datetime.now().year
    return legal


def test_section_job_keeps_edits_made_meanwhile(client: TestClient, llm: FakeLlm):
    cid = make_company(client, aspects=[])
    original = llm.section

    def edit_while_generating(prompt: str) -> dict[str, Any]:
        # пока модель думает, правят другой раздел
        with SessionLocal() as session:
            row = session.get(CompanyRow, cid)
            assert row
            data = copy.deepcopy(row.data)
            data["sections"]["legal"] = _legal_for(row)
            row.data = data
            session.commit()
        return original(prompt)

    llm.section = edit_while_generating  # type: ignore[method-assign]
    assert client.post(f"/api/companies/{cid}/aspects/security", json={}).json()["status"] == "done"
    sections = client.get(f"/api/companies/{cid}").json()["data"]["sections"]
    assert set(sections) == {"legal", "security"}


def test_section_job_refuses_when_facts_changed(client: TestClient, llm: FakeLlm):
    cid = make_company(client, aspects=[])
    original = llm.section

    def change_facts(prompt: str) -> dict[str, Any]:
        with SessionLocal() as session:
            row = session.get(CompanyRow, cid)
            assert row
            data = copy.deepcopy(row.data)
            data["tagline"] = "Новое предложение, пока генерировался раздел"
            row.data = data
            session.commit()
        return original(prompt)

    llm.section = change_facts  # type: ignore[method-assign]
    before = client.get(f"/api/companies/{cid}").json()["cost"]
    job = client.post(f"/api/companies/{cid}/aspects/security", json={}).json()
    assert job["status"] == "error"
    assert "изменили" in job["error"]
    company = client.get(f"/api/companies/{cid}").json()
    assert company["data"]["tagline"].startswith("Новое")
    assert "security" not in company["data"]["sections"]
    #за запрос всё равно заплатили
    assert company["cost"] == pytest.approx(before + 0.003)


def test_cost_limit_skips_remaining_sections(client: TestClient):
    cid = core_company(client, aspects=["legal", "privacy", "security"])
    client.post(f"/api/companies/{cid}/approve-facts")
    # хватает ровно на один раздел
    job = run_job(client, f"/api/companies/{cid}/sections", max_cost=0.003)
    assert job["status"] == "done"
    assert "лимит" in job["warning"]
    data = client.get(f"/api/companies/{cid}").json()["data"]
    assert list(data["sections"]) == ["legal"]


def test_brand_must_stay_unique_on_edit(client: TestClient):
    first = make_company(client, brand="Alpha", aspects=[])
    second = make_company(client, brand="Beta", aspects=[])
    data = client.get(f"/api/companies/{second}").json()["data"]
    data["brand"] = "alpha"
    data["contacts"]["email"] = "info@alpha.de"
    r = client.put(f"/api/companies/{second}", json=data)
    assert r.status_code == 400
    assert "бренд уже есть" in r.json()["detail"]
    # саму себя под тем же брендом сохранить можно
    own = client.get(f"/api/companies/{first}").json()["data"]
    assert client.put(f"/api/companies/{first}", json=own).status_code == 200


def test_add_section_to_ready_company(client: TestClient):
    cid = make_company(client, aspects=[])
    before = client.get(f"/api/companies/{cid}").json()
    r = client.post(f"/api/companies/{cid}/aspects/security", json={})
    assert r.json()["status"] == "done"
    after = client.get(f"/api/companies/{cid}").json()
    assert "security" in after["data"]["sections"]
    assert after["cost"] == pytest.approx(before["cost"] + 0.003)
    # общие факты не тронуты
    assert after["data"]["contacts"] == before["data"]["contacts"]
    assert after["data"]["people"] == before["data"]["people"]


def test_regenerate_and_remove_section(client: TestClient):
    cid = approved_company(client)
    assert client.post(f"/api/companies/{cid}/aspects/legal", json={}).json()["status"] == "done"
    # заглушка вернула тот же раздел, отпечаток не поменялся
    assert client.get(f"/api/companies/{cid}").json()["status"] == "approved"
    removed = client.delete(f"/api/companies/{cid}/aspects/legal")
    assert removed.status_code == 200
    assert "legal" not in removed.json()["data"]["sections"]
    assert client.delete(f"/api/companies/{cid}/aspects/legal").status_code == 404
    assert client.delete(f"/api/companies/{cid}/aspects/nope").status_code == 400
    assert client.post(f"/api/companies/{cid}/aspects/nope", json={}).status_code == 400
    assert client.post("/api/companies/999/aspects/legal", json={}).status_code == 404


def test_approve_is_blocked_by_joint_check(client: TestClient):
    cid = make_company(client)
    with SessionLocal() as session:
        row = session.get(CompanyRow, cid)
        assert row
        data = copy.deepcopy(row.data)
        data["sections"]["legal"]["imprint"]["represented_by"] = "Кто-то другой"
        row.data = data
        session.commit()
    r = client.post(f"/api/companies/{cid}/approve")
    assert r.status_code == 400
    assert "Утвердить нельзя" in r.json()["detail"]
    assert client.get(f"/api/companies/{cid}").json()["issues"]


def test_config_lists_aspects_and_labels(client: TestClient):
    body = client.get("/api/config").json()
    assert [a["key"] for a in body["aspects"]] == ["legal", "requisites", "privacy", "security", "references"]
    assert body["labels"]["testimonials"] == "Отзывы"


# ---------- сайт со всеми страницами ----------

def test_site_has_all_pages_and_footer_links(client: TestClient):
    cid = approved_company(client, brand="Zeta")
    job = make_site(client, cid)
    assert job["status"] == "done"
    sid = job["result_id"]
    for page in ("index", "product", "security", "references", "company", "legal", "privacy"):
        assert client.get(f"/preview/{sid}/{page}.html").status_code == 200
    index = client.get(f"/preview/{sid}/").text
    assert 'href="legal.html"' in index
    assert 'href="privacy.html"' in index
    assert "Сценарии использования" in client.get(f"/preview/{sid}/product.html").text
    assert client.get(f"/api/sites/{sid}").json()["report"]["ok"] is True


def test_site_without_sections_has_three_pages(client: TestClient):
    cid = approved_company(client, aspects=[])
    sid = make_site(client, cid)["result_id"]
    assert client.get(f"/preview/{sid}/security.html").status_code == 404
    assert client.get(f"/preview/{sid}/company.html").status_code == 200


def test_german_site_translates_every_section(client: TestClient):
    cid = approved_company(client, brand="Zeta")
    job = make_site(client, cid, language="de")
    assert job["status"] == "done"
    #карточка + 4 раздела = 5 запросов на перевод
    assert job["cost"] == pytest.approx(0.015)
    sid = job["result_id"]
    legal = client.get(f"/preview/{sid}/legal.html").text
    assert "Impressum" in legal
    assert "[de] " in legal
    assert "[de] " in client.get(f"/preview/{sid}/security.html").text
    refs = client.get(f"/preview/{sid}/references.html").text
    assert "Mit wem wir arbeiten" in refs
    # названия клиентов и имена авторов не переводятся
    assert "[de] Nordlicht" not in refs


def test_site_checks_cover_new_pages(client: TestClient):
    cid = approved_company(client)
    sid = make_site(client, cid)["result_id"]
    names = [c["name"] for c in client.get(f"/api/sites/{sid}").json()["report"]["checks"]]
    assert "Юридический раздел: выходные данные совпадают с карточкой" in names
    assert "Безопасность: все меры защиты на странице" in names
    assert "Клиенты: все клиенты и авторы отзывов на странице" in names


def test_site_check_finds_broken_new_page():
    data = example("kapitalklar")
    files = builder.render_site(data, data, "ru", "ocean", "sans")
    pages = {n: b.decode() for n, b in files.items() if n.endswith(".html")}
    pages["legal.html"] = pages["legal.html"].replace("Ларс Венцель", "")
    report = consistency.check_site(data, data, pages, files, "ru")
    failed = [c["name"] for c in report["checks"] if not c["ok"]]
    assert "Юридический раздел: выходные данные совпадают с карточкой" in failed


# ---------- новый аспект ----------

class Note(BaseModel):
    text: str = Field(min_length=10)


class NoteAspect(Aspect):
    key = "notes"
    number = 99
    title = "Заметки"
    model = Note
    skeleton = '{"text": "заметка"}'
    pages: tuple[Page, ...] = (Page("notes", "notes.html", {"ru": "Заметки", "de": "Notizen"}, "nav", "notes"),)
    translatable = frozenset({"text"})
    labels = {"notes": "Заметки"}

    def prompt(self, ctx: Ctx) -> str:
        return "Напиши короткую заметку о компании."

    def meta(self, data: dict[str, Any], facts: dict[str, Any]) -> str:
        return str(data["text"])

    def check_site(self, orig: dict[str, Any], card: dict[str, Any], texts: dict[str, str]) -> list[dict[str, Any]]:
        text = card["sections"]["notes"]["text"]
        return [result("Заметки: текст на странице", norm(text) in texts["notes.html"])]


@pytest.fixture
def notes_aspect(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    registry.register(NoteAspect())
    body = "<h1>{{ ptitle }}</h1><p>{{ section.text }}</p>"
    template = '{% extends "base.html" %}{% block content %}' + body + "{% endblock %}"
    extra = DictLoader({"notes.html": template})
    sources: list[Any] = [builder.env.loader, extra]
    monkeypatch.setattr(builder.env, "loader", ChoiceLoader(sources))
    yield
    registry.unregister("notes")


def test_new_aspect_works_end_to_end(client: TestClient, llm: FakeLlm, notes_aspect: None):
    llm.custom["notes"] = {"text": "Заметка про нашу компанию и её клиентов."}

    config = client.get("/api/config").json()
    assert "notes" in [a["key"] for a in config["aspects"]]
    assert config["labels"]["notes"] == "Заметки"

    cid = approved_company(client, aspects=["notes"])
    assert client.get(f"/api/companies/{cid}").json()["data"]["sections"]["notes"] == llm.custom["notes"]

    sid = make_site(client, cid)["result_id"]
    assert "Заметка про нашу компанию" in client.get(f"/preview/{sid}/notes.html").text
    assert 'href="notes.html"' in client.get(f"/preview/{sid}/").text
    assert client.get(f"/api/sites/{sid}").json()["report"]["ok"] is True

    # перевод подхватывает поля нового аспекта сам
    de = make_site(client, cid, language="de")["result_id"]
    assert "[de] Заметка" in client.get(f"/preview/{de}/notes.html").text

    assert "notes" in build_schema()["properties"]["sections"]["properties"]


def test_aspect_dependencies(notes_aspect: None):
    class Second(NoteAspect):
        key = "second"
        requires = ("notes",)
        pages = ()

    registry.register(Second())
    try:
        with pytest.raises(AppError, match="требует"):
            registry.order(["second"])
        assert [a.key for a in registry.order(["second", "notes"])] == ["notes", "second"]
        assert [a.key for a in registry.order(["second"], present=["notes"])] == ["second"]
        assert registry.dependents("notes", ["notes", "second"]) == ["second"]
    finally:
        registry.unregister("second")


def test_duplicate_aspect_is_rejected(notes_aspect: None):
    with pytest.raises(ValueError, match="уже зарегистрирован"):
        registry.register(NoteAspect())


@pytest.mark.parametrize("raw", [
    "2. Порядок оказания услуг",
    "2) Порядок оказания услуг",
    "§ 2 Порядок оказания услуг",
])
def test_terms_titles_lose_model_numbers(raw: str):
    from sitegen.aspects.legal import TermsSection

    assert TermsSection(title=raw, text="т" * 60).title == "Порядок оказания услуг"


def test_old_numbered_terms_render_once():
    from sitegen.core import builder

    data = copy.deepcopy(example("kapitalklar"))
    data["sections"]["legal"]["terms"][1]["title"] = "2. Порядок оказания услуг"
    page = builder.render_site(data, data, "ru", "ocean", "sans")["legal.html"].decode()
    assert "2. Порядок оказания услуг" in page
    assert "2. 2." not in page


def test_publications_need_text():
    pubs = copy.deepcopy(example("kapitalklar")["sections"]["references"]["publications"])
    pubs[0]["body"] = pubs[0]["body"][:1]
    assert any("нет текста" in i for i in issues_with(references__publications=pubs))


def test_publication_opens_on_site():
    from sitegen.core import builder

    data = example("kapitalklar")
    page = builder.render_site(data, data, "ru", "ocean", "sans")["references.html"].decode()
    assert page.count('<details class="pub">') == len(data["sections"]["references"]["publications"])
    assert data["sections"]["references"]["publications"][0]["body"][2] in page


def test_old_publication_without_text_still_renders():
    from sitegen.core import builder

    data = copy.deepcopy(example("kapitalklar"))
    for p in data["sections"]["references"]["publications"]:
        p.pop("body")
    page = builder.render_site(data, data, "ru", "ocean", "sans")["references.html"].decode()
    assert '<details class="pub">' not in page
    assert data["sections"]["references"]["publications"][0]["title"] in page
