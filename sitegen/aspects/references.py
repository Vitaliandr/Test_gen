from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from sitegen.aspects.base import Aspect, Ctx, Page, result
from sitegen.core.text import norm


class Client(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    segment: str = Field(min_length=10, max_length=200)
    since_year: int = Field(ge=1990, le=2100)
    description: str = Field(min_length=30, max_length=400)


class Testimonial(BaseModel):
    quote: str = Field(min_length=30, max_length=500)
    author_name: str = Field(min_length=3, max_length=80)
    author_role: str = Field(min_length=3, max_length=100)
    client: str = Field(min_length=2, max_length=80)


class CaseStudy(BaseModel):
    title: str = Field(min_length=10, max_length=160)
    client: str = Field(min_length=2, max_length=80)
    challenge: str = Field(min_length=40, max_length=500)
    approach: str = Field(min_length=40, max_length=600)
    result: str = Field(min_length=40, max_length=500)


Paragraph = Annotated[str, Field(min_length=60, max_length=700)]


class Publication(BaseModel):
    title: str = Field(min_length=10, max_length=200)
    kind: Literal["article", "whitepaper", "report", "talk"]
    year: int = Field(ge=1990, le=2100)
    author: str = Field(min_length=3, max_length=80)
    summary: str = Field(min_length=30, max_length=400)
    # у старых карточек текста нет, тогда не раскрываем
    body: list[Paragraph] = Field(default_factory=list, max_length=4)


class References(BaseModel):
    clients: list[Client] = Field(min_length=3, max_length=6)
    testimonials: list[Testimonial] = Field(min_length=2, max_length=4)
    cases: list[CaseStudy] = Field(min_length=2, max_length=3)
    publications: list[Publication] = Field(min_length=2, max_length=5)


class ReferencesAspect(Aspect):
    key = "references"
    number = 8
    title = "Клиенты, отзывы, кейсы и публикации"
    model = References
    pages = (Page("references", "references.html", {"ru": "Клиенты и кейсы", "de": "Kunden & Referenzen"}, "nav", "references"),)
    translatable = frozenset({
        "segment", "description", "quote", "author_role", "challenge", "approach", "result", "title", "summary",
        "body",
    })  # fmt: skip
    labels = {
        "references": "Клиенты и кейсы", "clients": "Клиенты", "segment": "Сегмент", "since_year": "Работаем с года",
        "testimonials": "Отзывы", "quote": "Цитата", "author_name": "Автор отзыва", "author_role": "Должность автора",
        "client": "Клиент", "cases": "Кейсы", "challenge": "Задача", "approach": "Что сделали", "result": "Результат",
        "publications": "Публикации", "kind": "Тип", "year": "Год", "author": "Автор из команды", "body": "Текст публикации",
        "description": "Описание",
    }  # fmt: skip
    strings = {
        "ru": {"clients": "С кем мы работаем", "since": "клиент с", "testimonials": "Отзывы клиентов",
               "cases": "Кейсы", "challenge": "Задача", "approach": "Что сделали", "result": "Результат",
               "publications": "Публикации", "by": "Автор", "kind_article": "Статья", "kind_whitepaper": "Исследование",
               "kind_report": "Отчёт", "kind_talk": "Доклад", "read": "Читать"},
        "de": {"clients": "Mit wem wir arbeiten", "since": "Kunde seit", "testimonials": "Stimmen unserer Kunden",
               "cases": "Fallstudien", "challenge": "Aufgabe", "approach": "Vorgehen", "result": "Ergebnis",
               "publications": "Veröffentlichungen", "by": "Autor", "kind_article": "Artikel",
               "kind_whitepaper": "Whitepaper", "kind_report": "Bericht", "kind_talk": "Vortrag", "read": "Lesen"},
    }  # fmt: skip
    skeleton = """Структура JSON:
{
  "clients": [{"name": "выдуманное название организации", "segment": "кто это, например семейный офис", "since_year": 2024, "description": "чем занимается и как пользуется услугой"}],
  "testimonials": [{"quote": "отзыв, 1-3 предложения", "author_name": "Имя Фамилия", "author_role": "должность", "client": "название клиента из списка clients"}],
  "cases": [{"title": "название кейса", "client": "название клиента из списка clients", "challenge": "задача", "approach": "что сделали", "result": "что получил клиент"}],
  "publications": [{"title": "название", "kind": "article или whitepaper или report или talk", "year": 2025, "author": "имя сотрудника из команды", "summary": "о чём, 1-2 предложения", "body": ["абзац 1", "абзац 2", "абзац 3"]}]
}
clients: 3-6, testimonials: 2-4, cases: 2-3, publications: 2-5."""

    def prompt(self, ctx: Ctx) -> str:
        return f"""Подготовь раздел о клиентах: список клиентов, отзывы, кейсы и публикации компании.
Правила:
- всё вымышлено: названия организаций и имена авторов отзывов придумай, не используй реальные компании и людей
- организации должны подходить аудитории продукта: {ctx.facts['audience']}
- отзывы и кейсы описывай качественно, без обещаний и цифр доходности, без слов «гарантируем доходность»
- в testimonials и cases поле client это название из списка clients без изменений
- авторы отзывов не из команды компании
- автор публикации это сотрудник из фактов, имя точно как в фактах
- годы клиентов и публикаций: не раньше {ctx.facts['founding_year']} (год основания) и не позже {datetime.now().year}
- не добавляй ссылки и адреса сайтов
- body у публикации: 3-4 абзаца по 2-4 предложения с основными мыслями публикации, на сайте их читают целиком
- результат кейса не должен противоречить ограничениям продукта из фактов"""

    def check(self, ctx: Ctx, data: Any) -> list[str]:
        issues = []
        names = [c.name for c in data.clients]
        if len({n.lower() for n in names}) != len(names):
            issues.append("названия клиентов повторяются")
        for t in data.testimonials:
            if t.client not in names:
                issues.append(f"отзыв ссылается на клиента «{t.client}», которого нет в списке")
        for c in data.cases:
            if c.client not in names:
                issues.append(f"кейс ссылается на клиента «{c.client}», которого нет в списке")
        authors = [t.author_name for t in data.testimonials]
        if len(set(authors)) != len(authors):
            issues.append("авторы отзывов повторяются")
        team = set(ctx.people_names)
        if any(a in team for a in authors):
            issues.append("автор отзыва клиента не может быть сотрудником компании")
        if {ctx.facts["brand"].lower(), ctx.facts["legal_name"].lower()} & {n.lower() for n in names}:
            issues.append("клиентом названа сама компания")
        low, high = ctx.facts["founding_year"], datetime.now().year
        for c in data.clients:
            if not low <= c.since_year <= high:
                issues.append(f"клиент «{c.name}»: год {c.since_year} вне диапазона {low}-{high}")
        for p in data.publications:
            if not low <= p.year <= high:
                issues.append(f"публикация «{p.title[:30]}»: год {p.year} вне диапазона {low}-{high}")
            if p.author not in team:
                issues.append(f"автор публикации «{p.author}» не из команды")
            if len(p.body) < 3:
                issues.append(f"у публикации «{p.title[:30]}» нет текста, нужно 3-4 абзаца")
        return issues

    def meta(self, data: dict[str, Any], facts: dict[str, Any]) -> str:
        return str(data["clients"][0]["description"])

    def check_site(self, orig: dict[str, Any], card: dict[str, Any], texts: dict[str, str]) -> list[dict[str, Any]]:
        page = texts.get("references.html", "")
        sec = card["sections"]["references"]
        names = [c["name"] for c in sec["clients"]]
        authors = [t["author_name"] for t in sec["testimonials"]]
        titles = [c["title"] for c in sec["cases"]] + [p["title"] for p in sec["publications"]]
        titles += [p["body"][0] for p in sec["publications"] if p.get("body")]
        miss_clients = [n for n in names + authors if norm(n) not in page]
        miss_titles = [t for t in titles if norm(t) not in page]
        return [
            result("Клиенты: все клиенты и авторы отзывов на странице", not miss_clients, ", ".join(miss_clients)),
            result("Клиенты: все кейсы и публикации с текстом на странице", not miss_titles, ", ".join(miss_titles)),
        ]
