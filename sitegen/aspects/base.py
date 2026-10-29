import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from sitegen.core.text import BAD, walk_strings

# обещать доходность нельзя ни в каком виде
CLAIMS = re.compile(
    r"гарантир\w+\s+(?:\w+\s+)?(?:доходност|прибыл)"
    r"|garantier\w*\s+(?:\w+\s+)?(?:Rendite|Gewinn|Ertrag)"
    r"|(?:Rendite|Gewinn|Ertrag)\w*\s+(?:\w+\s+)?garantier",
    re.I,
)
URL = re.compile(r"https?://|www\.", re.I)
#на сайте ничего этого нет: кабинета, входа, загрузки, форм
# «компания зарегистрирована» норм, ловим только «зарегистрируйтесь» и т.п.
FEATURE = re.compile(
    r"личн\w+ кабинет|клиентск\w+ портал|Kundenportal|Nutzerkonto|Benutzerkonto|Kundenkonto|Kundenlogin"
    r"|зарегистрируйтесь|регистрац\w+ (?:на сайте|пользовател\w+|аккаунт\w*)|войдите|вход в (?:систему|аккаунт)"
    r"|registrieren Sie sich|\beinloggen\b|melden Sie sich an"
    r"|загрузите\b|загрузк\w* (?:пользовательск\w+ )?файл\w*|загру\w+ (?:свои |собственн\w+ )?файл\w*"
    r"|\bhochlad\w*|\bUpload\w*"
    r"|форм\w+ (?:заявк|обратн|регистрац|запрос)\w*|оставьте заявку|заполните форму|Kontaktformular\w*|\bFormular\w*",
    re.I,
)
#«мы не сертифицированы» это честно, не ругаемся
NEGATION = re.compile(
    r"(?<!\w)(?:не|нет|без|ни|никак\w*|отсутств\w*|kein\w*|nicht|ohne|weder|no|not|without)(?!\w)", re.I
)
SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")


def affirmed(pattern: re.Pattern[str], texts: Iterable[str]) -> list[str]:
    # предложения с «не» и «нет» пропускаем
    found = []
    for text in texts:
        for sentence in SENTENCE.split(text):
            if NEGATION.search(sentence):
                continue
            found += [m.group(0) for m in pattern.finditer(sentence)]
    return found


@dataclass(frozen=True)
class Page:
    key: str
    file: str
    titles: dict[str, str]
    # nav в меню, footer в подвале
    placement: Literal["nav", "footer"] = "nav"
    #у главной, продукта и контактов пусто
    aspect: str = ""


@dataclass
class Ctx:
    # facts это карточка без sections
    facts: dict[str, Any]
    sections: dict[str, Any] = field(default_factory=dict)
    language: str = "ru"

    @classmethod
    def from_card(cls, data: dict[str, Any]) -> "Ctx":
        facts = {k: v for k, v in data.items() if k != "sections"}
        return cls(facts, dict(data.get("sections", {})), data.get("language", "ru"))

    @property
    def people_names(self) -> list[str]:
        return [p["name"] for p in self.facts["people"]]

    @property
    def ceo(self) -> str:
        return str(next(p["name"] for p in self.facts["people"] if p["level"] == "ceo"))

    @property
    def product_text(self) -> str:
        return " ".join(walk_strings(self.facts.get("product", {})))


#целиком раздел модели не шлём, хватит начала
DIGEST_CHARS = 1500


def digest(section: Any) -> str:
    text = " | ".join(s for s in walk_strings(section) if s)
    return text if len(text) <= DIGEST_CHARS else text[:DIGEST_CHARS] + "..."


def facts_block(ctx: Ctx) -> str:
    f = ctx.facts
    ct = f["contacts"]
    product = f["product"]
    people = "; ".join(f"{p['name']} ({p['role']})" for p in f["people"])
    scenarios = "; ".join(f"{s['title']}: {s['result']}" for s in product["scenarios"])
    faq = "\n".join(f"  - {q['question']} {q['answer']}" for q in f["faq"])
    block = f"""Утверждённые факты компании, им нельзя противоречить:
- бренд: {f['brand']}, юридическое название: {f['legal_name']}, основана в {f['founding_year']}, сотрудников: {f['employee_count']}
- адрес: {ct['street']}, {ct['postal_code']} {ct['city']}; телефон {ct['phone']}; почта {ct['email']}
- директор: {ctx.ceo}; команда: {people}
- предложение: {f['tagline']}. {f['value_proposition']}
- история: {f['history']}
- специализация: {f['specialization']}
- аудитория: {f['audience']}
- проблема клиента: {f['client_problem']}
- продукт: {product['name']}. {product['summary']}
- входные данные продукта: {'; '.join(product['inputs'])}
- как работает: {'; '.join(product['process'])}
- результат: {'; '.join(product['outputs'])}
- ограничения продукта: {'; '.join(product['limitations'])}
- сценарии: {scenarios}
- вопросы и ответы:
{faq}"""
    if ctx.sections:
        # в готовых разделах тоже факты, сроки например
        done = "\n".join(f"- {key}: {digest(value)}" for key, value in ctx.sections.items())
        block += f"\n\nУже готовые разделы сайта, с ними тоже нельзя расходиться:\n{done}"
    return block


def unsupported_features(ctx: Ctx, texts: Iterable[str]) -> list[str]:
    known = {m.group(0).lower() for m in FEATURE.finditer(ctx.product_text)}
    found = {m.lower() for m in affirmed(FEATURE, texts)}
    return sorted(found - known)


def result(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


#новый раздел = подкласс + registry.register(), больше ничего править не надо
class Aspect:

    key: str
    number: int
    title: str
    model: type[BaseModel]
    skeleton: str
    requires: tuple[str, ...] = ()
    pages: tuple[Page, ...] = ()
    # имена и названия сюда не класть, их не переводим
    translatable: frozenset[str] = frozenset()
    labels: dict[str, str] = {}
    strings: dict[str, dict[str, str]] = {}
    #True = раздел собирает build(), модель не дёргаем
    by_code: bool = False

    def prompt(self, ctx: Ctx) -> str:
        raise NotImplementedError

    def build(self, ctx: Ctx) -> dict[str, Any]:
        raise NotImplementedError

    def check(self, ctx: Ctx, data: Any) -> list[str]:
        return []

    def meta(self, data: dict[str, Any], facts: dict[str, Any]) -> str:
        return ""

    def check_site(self, orig: dict[str, Any], card: dict[str, Any], texts: dict[str, str]) -> list[dict[str, Any]]:
        return []

    def issues(self, ctx: Ctx, data: BaseModel) -> list[str]:
        out = []
        for s in walk_strings(data.model_dump()):
            if BAD.search(s):
                out.append(f"остался шаблонный фрагмент: «{s[:40]}»")
            if affirmed(CLAIMS, [s]):
                out.append(f"обещание доходности: «{s[:60]}»")
            if URL.search(s):
                out.append("ссылки не добавляем, они были бы выдуманными")
        return out + self.check(ctx, data)
