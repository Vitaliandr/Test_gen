import re
from typing import Any

from pydantic import BaseModel, Field

from sitegen import catalog
from sitegen.aspects.base import Aspect, Ctx, Page, affirmed, result, unsupported_features
from sitegen.core.text import norm, walk_strings

#форм, рассылок и аналитики на сайте нет
NOT_ON_SITE = re.compile(
    r"форм\w+ обратной связи|Kontaktformular|Newsletter|рассылк|регистрац|Registrierung|Webanalyse|Tracking"
    r"|трекинг|веб-аналитик|личн\w+ кабинет",
    re.I,
)
ANALYTICS_TOOLS = re.compile(r"Google Analytics|Matomo|Hotjar|Facebook Pixel|Meta Pixel|Яндекс\.?\s?Метрик", re.I)


class DataItem(BaseModel):
    category: str = Field(min_length=3, max_length=120)
    purpose: str = Field(min_length=20, max_length=300)
    legal_basis: str = Field(min_length=5, max_length=200)
    # сбор, запись, хранение и т.д., для 152-ФЗ обязательно
    actions: str = Field(default="", max_length=300)
    retention: str = Field(min_length=3, max_length=200)


class PolicySection(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    text: str = Field(min_length=60, max_length=2000)


class PrivacyPolicy(BaseModel):
    intro: str = Field(min_length=40, max_length=600)
    controller_note: str = Field(min_length=20, max_length=400)
    data_processed: list[DataItem] = Field(min_length=2, max_length=6)
    recipients: list[str] = Field(min_length=1, max_length=5)
    rights: list[str] = Field(min_length=4, max_length=8)
    cookies_statement: str = Field(min_length=30, max_length=500)
    contact_for_requests: str = Field(min_length=30, max_length=400)
    #разделы по закону страны, для GDPR не нужны
    sections: list[PolicySection] = Field(default_factory=list, max_length=12)
    effective_year: int = Field(ge=2000, le=2100)


def profile(country: str) -> dict[str, Any]:
    info: dict[str, Any] = catalog.COUNTRIES.get(country, catalog.COUNTRIES["DE"])["privacy"]
    return info


class PrivacyAspect(Aspect):
    key = "privacy"
    number = 6
    title = "Персональные данные и политики обработки"
    model = PrivacyPolicy
    pages = (
        Page("privacy", "privacy.html", {"ru": "Обработка персональных данных", "de": "Datenschutz"}, "footer", "privacy"),
    )
    translatable = frozenset({
        "intro", "controller_note", "category", "purpose", "legal_basis", "actions", "retention", "recipients",
        "rights", "cookies_statement", "contact_for_requests", "title", "text",
    })  # fmt: skip
    labels = {
        "privacy": "Персональные данные", "intro": "Вступление", "controller_note": "Кто отвечает за обработку",
        "data_processed": "Какие данные обрабатываются", "category": "Категория данных", "purpose": "Цель",
        "legal_basis": "Правовое основание", "actions": "Действия с данными", "retention": "Срок хранения",
        "recipients": "Кто получает данные", "rights": "Права субъекта данных", "cookies_statement": "Cookie и аналитика",
        "contact_for_requests": "Куда обращаться", "sections": "Разделы политики",
    }  # fmt: skip
    strings = {
        "ru": {"controller": "Ответственный за обработку", "data": "Какие данные и зачем", "category": "Данные",
               "purpose": "Цель", "basis": "Основание", "actions": "Действия", "retention": "Срок хранения",
               "recipients": "Кто получает данные", "rights": "Ваши права", "cookies": "Cookie и аналитика",
               "requests": "Запросы и обращения", "write_to": "Пишите на", "effective": "Действует с"},
        "de": {"controller": "Verantwortlicher", "data": "Welche Daten und wozu", "category": "Daten",
               "purpose": "Zweck", "basis": "Rechtsgrundlage", "actions": "Vorgänge", "retention": "Speicherdauer",
               "recipients": "Empfänger", "rights": "Ihre Rechte", "cookies": "Cookies und Analyse",
               "requests": "Anfragen", "write_to": "Schreiben Sie an", "effective": "Gültig seit"},
    }  # fmt: skip
    skeleton = """Структура JSON:
{
  "intro": "о чём политика, по какому закону и для кого, 2-3 предложения",
  "controller_note": "кто оператор (ответственный за обработку): юридическое название компании, 1-2 предложения",
  "data_processed": [
    {"category": "категория данных", "purpose": "цель обработки", "legal_basis": "правовое основание по закону страны",
     "actions": "действия с данными: сбор, запись, хранение, уничтожение", "retention": "срок хранения"}
  ],
  "recipients": ["кто может получать данные, обобщённо"],
  "rights": ["права субъекта данных, по одному на пункт"],
  "cookies_statement": "что с cookie и аналитикой на сайте",
  "contact_for_requests": "как направить запрос, без адреса почты, его добавит система",
  "sections": [{"title": "заголовок раздела", "text": "текст раздела, 3-6 предложений"}],
  "effective_year": 2026
}
data_processed: от 2 до 6 пунктов, rights: от 4 до 8 пунктов."""

    def prompt(self, ctx: Ctx) -> str:
        prof = profile(ctx.facts["country"])
        required = "; ".join(title for title, _ in prof["sections"])
        sections_rule = (
            f"- в sections обязательно разделы с такими заголовками: {required}" if required
            else "- sections можно оставить пустым списком"
        )
        must = "; ".join(label for label, _ in prof["must_mention"])
        must_rule = f"\n- в тексте обязательно должно прозвучать: {must}" if must else ""
        return f"""Подготовь политику обработки персональных данных для сайта компании по закону: {prof['law']}.
Это общий шаблон, не юридическая консультация.
Сайт статический: на нём нет форм, регистрации, личного кабинета, рассылок, cookie и аналитики.
Правила:
- перечисли только то, что реально происходит: серверные журналы при открытии страниц и переписка по почте или телефону
- {prof['basis_hint']}
- в actions для каждого пункта перечисли действия с данными
- в controller_note назови оператора «{ctx.facts['legal_name']}»
- в cookies_statement прямо напиши, что сайт не использует cookie и инструменты аналитики
- права: {prof['rights']}
{sections_rule}{must_rule}
- не упоминай формы, рассылки, регистрацию и личный кабинет
- адрес почты и телефон не пиши, система добавит контакты из фактов"""

    def check(self, ctx: Ctx, data: Any) -> list[str]:
        prof = profile(ctx.facts["country"])
        issues = []
        basis = re.compile(prof["basis_pattern"], re.I)
        if not any(basis.search(i.legal_basis) for i in data.data_processed):
            issues.append(f"в правовых основаниях нет ссылки на {prof['law']}")
        processed = [f"{i.category}. {i.purpose}" for i in data.data_processed]
        if affirmed(NOT_ON_SITE, processed):
            issues.append("в обрабатываемых данных то, чего на сайте нет: формы, рассылки, регистрация или аналитика")
        if affirmed(ANALYTICS_TOOLS, [data.cookies_statement]):
            issues.append("в тексте про cookie названы инструменты аналитики, а на сайте их нет")
        if ctx.facts["legal_name"] not in f"{data.intro} {data.controller_note}":
            issues.append(f"не указано, что оператор это {ctx.facts['legal_name']}")

        text = " ".join(walk_strings(data.model_dump()))
        for label, pattern in prof["must_mention"]:
            if not re.search(pattern, text, re.I):
                issues.append(f"в политике не сказано: {label}")
        titles = " | ".join(s.title for s in data.sections)
        for title, pattern in prof["sections"]:
            if not re.search(pattern, titles, re.I):
                issues.append(f"нет раздела «{title}»")
        if prof["sections"] and not all(i.actions for i in data.data_processed):
            issues.append("у пунктов обработки не перечислены действия с данными")

        found = unsupported_features(ctx, walk_strings(data.model_dump()))
        if found:
            issues.append(f"упомянуты функции, которых нет у продукта: {', '.join(found)}")
        return issues

    def meta(self, data: dict[str, Any], facts: dict[str, Any]) -> str:
        return str(data["intro"])

    def check_site(self, orig: dict[str, Any], card: dict[str, Any], texts: dict[str, str]) -> list[dict[str, Any]]:
        page = texts.get("privacy.html", "")
        ct = orig["contacts"]
        facts = [orig["legal_name"], ct["street"], ct["postal_code"], ct["city"], ct["email"]]
        missing = [f for f in facts if norm(f) not in page]
        sec = card["sections"]["privacy"]
        parts = [i["category"] for i in sec["data_processed"]] + [s["title"] for s in sec.get("sections", [])]
        no_parts = [p for p in parts if norm(p) not in page]
        return [
            result("Персональные данные: оператор и контакты совпадают с карточкой", not missing, ", ".join(missing)),
            result("Персональные данные: все категории данных и разделы на странице", not no_parts, ", ".join(no_parts)),
        ]
