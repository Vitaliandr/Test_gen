import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from sitegen import catalog
from sitegen.aspects.base import Aspect, Ctx, Page, result, unsupported_features
from sitegen.core.text import norm, strip_number, walk_strings

# номера есть только в реквизитах, модели их писать нельзя
REGISTRY_NUMBERS = re.compile(r"\bHR[AB]\s*\d|\bDE\s?\d{9}\b|USt\.?-?Id|\bИНН\b|\bОГРН\b", re.I)


class TermsSection(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    text: str = Field(min_length=60, max_length=1500)

    @field_validator("title")
    @classmethod
    def no_number(cls, v: str) -> str:
        return strip_number(v)


class Imprint(BaseModel):
    represented_by: str = Field(min_length=3, max_length=80)
    content_responsible: str = Field(min_length=3, max_length=80)
    liability_note: str = Field(min_length=40, max_length=800)
    dispute_note: str = Field(min_length=40, max_length=800)


class LegalDocs(BaseModel):
    imprint: Imprint
    terms_intro: str = Field(min_length=40, max_length=600)
    terms: list[TermsSection] = Field(min_length=5, max_length=9)
    effective_year: int = Field(ge=2000, le=2100)


class LegalAspect(Aspect):
    key = "legal"
    number = 2
    title = "Юридические документы"
    model = LegalDocs
    pages = (
        Page("legal", "legal.html", {"ru": "Правовая информация", "de": "Rechtliche Hinweise"}, "footer", "legal"),
    )
    translatable = frozenset({"liability_note", "dispute_note", "terms_intro", "title", "text"})
    labels = {
        "legal": "Юридические документы", "imprint": "Выходные данные", "represented_by": "Представитель (директор)",
        "content_responsible": "Ответственный за содержание", "liability_note": "Ответственность за содержание",
        "dispute_note": "Споры", "terms_intro": "Условия: вступление", "terms": "Условия использования",
        "text": "Текст", "title": "Заголовок", "effective_year": "Действуют с года",
    }  # fmt: skip
    strings = {
        "ru": {"imprint": "Выходные данные", "imprint_ru": "Сведения о компании", "terms": "Условия использования услуг", "represented": "Представитель",
               "responsible": "Ответственный за содержание", "effective": "Действуют с"},
        "de": {"imprint": "Impressum", "imprint_ru": "Angaben zum Unternehmen", "terms": "Allgemeine Geschäftsbedingungen", "represented": "Vertreten durch",
               "responsible": "Verantwortlich für den Inhalt", "effective": "Gültig seit"},
    }  # fmt: skip
    skeleton = """Структура JSON:
{
  "imprint": {
    "represented_by": "имя директора, точно как в фактах",
    "content_responsible": "имя кого-то из команды",
    "liability_note": "ответственность за содержание сайта, 2-3 предложения",
    "dispute_note": "порядок разрешения споров с потребителями, 2-3 предложения"
  },
  "terms_intro": "к кому и к чему относятся условия, 2-3 предложения",
  "terms": [{"title": "заголовок пункта без номера, нумерацию добавит система", "text": "текст пункта, 3-5 предложений"}],
  "effective_year": 2026
}
terms: от 5 до 9 пунктов."""

    def prompt(self, ctx: Ctx) -> str:
        legal = catalog.COUNTRIES.get(ctx.facts["country"], catalog.COUNTRIES["DE"])["legal"]
        return f"""Подготовь юридический раздел сайта: {legal['imprint']} и условия использования услуг.
Это общий шаблон, не юридическая консультация.
Правила:
- представитель компании (руководитель): {ctx.ceo}
- ответственный за содержание: один из сотрудников из фактов
- в dispute_note опиши {legal['dispute']}
- не пиши регистрационные, налоговые номера и номера записей в реестре, их нет в фактах
- в условиях называй компанию «{ctx.facts['legal_name']}», продукт «{ctx.facts['product']['name']}», применимое право: {legal['law']}
- пункты условий: предмет услуг, порядок оказания, обязанности сторон, ответственность, срок и расторжение, применимое право, заключительные положения
- условия соответствуют продукту и его ограничениям, ничего не обещай сверх описания
- не заявляй инвестиционных консультаций и гарантий результата
- не упоминай личный кабинет и другие функции, которых у продукта нет"""

    def check(self, ctx: Ctx, data: Any) -> list[str]:
        issues = []
        imp = data.imprint
        if imp.represented_by != ctx.ceo:
            issues.append(f"в выходных данных представитель должен быть директор: {ctx.ceo}")
        if imp.content_responsible not in ctx.people_names:
            issues.append("ответственный за содержание должен быть из команды")
        terms = " ".join([data.terms_intro, *(f"{t.title} {t.text}" for t in data.terms)])
        if ctx.facts["legal_name"] not in terms:
            issues.append(f"в условиях нет юридического названия {ctx.facts['legal_name']}")
        if ctx.facts["product"]["name"] not in terms:
            issues.append(f"в условиях продукт должен называться как в фактах: {ctx.facts['product']['name']}")
        #неизвестную страну и так поймает проверка контактов
        markers = catalog.COUNTRIES.get(ctx.facts["country"], {}).get("law_markers")
        if markers and not re.search(markers, terms, re.I):
            issues.append("в условиях не указано применимое право страны компании")
        if REGISTRY_NUMBERS.search(" ".join(walk_strings(data.model_dump()))):
            issues.append("в тексте номера из реестров, их нельзя выдумывать")
        if not ctx.facts["founding_year"] <= data.effective_year <= datetime.now().year:
            issues.append("год начала действия условий раньше основания компании или в будущем")
        found = unsupported_features(ctx, walk_strings(data.model_dump()))
        if found:
            issues.append(f"упомянуты функции, которых нет у продукта: {', '.join(found)}")
        return issues

    def meta(self, data: dict[str, Any], facts: dict[str, Any]) -> str:
        return str(data["terms_intro"])

    def check_site(self, orig: dict[str, Any], card: dict[str, Any], texts: dict[str, str]) -> list[dict[str, Any]]:
        page = texts.get("legal.html", "")
        ct = orig["contacts"]
        imp = orig["sections"]["legal"]["imprint"]
        facts = [orig["legal_name"], ct["street"], ct["postal_code"], ct["city"], ct["phone"], ct["email"]]
        facts += [imp["represented_by"], imp["content_responsible"]]
        missing = [f for f in facts if norm(f) not in page]
        titles = [t["title"] for t in card["sections"]["legal"]["terms"]]
        no_terms = [t for t in titles if norm(t) not in page]
        return [
            result("Юридический раздел: выходные данные совпадают с карточкой", not missing, ", ".join(missing)),
            result("Юридический раздел: все пункты условий на странице", not no_terms, ", ".join(no_terms)),
        ]
