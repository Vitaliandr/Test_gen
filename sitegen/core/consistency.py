import html
import re
from collections.abc import Iterable
from typing import Any

from sitegen import catalog
from sitegen.aspects import registry
from sitegen.aspects.base import FEATURE, Ctx, affirmed, result
from sitegen.card import Company, CompanyContent, Contacts
from sitegen.core import builder
from sitegen.core.text import BAD, blank_paths, norm, slugify, split_tagline, walk_strings

__all__ = ["BAD", "check_company", "check_content", "check_contacts", "check_sections", "check_site", "page_text"]


def check_content(c: CompanyContent, legal_form: str | None = None, existing_brands: Iterable[str] = ()) -> list[str]:
    issues = []
    #pydantic смотрит длину, а пустой пункт в списке пропускает
    blank = blank_paths(c.model_dump())
    if blank:
        issues.append(f"пустые поля: {', '.join(blank[:8])}")
    for s in walk_strings(c.model_dump()):
        if BAD.search(s):
            issues.append(f"остался шаблонный фрагмент: «{s[:40]}»")
    names = [p.name.strip().lower() for p in c.people]
    if len(set(names)) != len(names):
        issues.append("имена сотрудников повторяются")
    if str(c.founding_year) not in c.history:
        issues.append(f"в истории не упомянут год основания {c.founding_year}")
    if legal_form and legal_form.split()[0] not in c.legal_name:
        issues.append(f"в юридическом названии должна быть форма {legal_form}")
    if c.brand.strip().lower() in {b.strip().lower() for b in existing_brands}:
        issues.append("такой бренд уже есть, придумай другой")
    # это всё пойдёт на сайт, а форм там нет
    found = sorted({m.lower() for m in affirmed(FEATURE, walk_strings(c.model_dump()))})
    if found:
        issues.append(
            f"описаны функции, которых нет на сайте: {', '.join(found)}; связь с компанией только по почте и телефону"
        )
    return issues


def check_contacts(country: str, ct: Contacts, brand: str) -> list[str]:
    info = catalog.COUNTRIES.get(country)
    if not info:
        return [f"неизвестная страна: {country}"]
    city = info["cities"].get(ct.city)
    if not city:
        return [f"город «{ct.city}» не из каталога страны {country}"]

    issues = []
    digits = re.sub(r"\D", "", ct.phone)
    prefix = info["phone_code"] + city["area"]
    if not digits.startswith(prefix) or not 10 <= len(digits) <= 13:
        issues.append(f"телефон {ct.phone} не подходит городу {ct.city} (код +{prefix})")
    if len(ct.postal_code) != info["postal_digits"] or not any(ct.postal_code.startswith(p) for p in city["plz"]):
        issues.append(f"индекс {ct.postal_code} не подходит городу {ct.city}")
    domain = f"{slugify(brand)}.{info['tld']}"
    m = re.fullmatch(r"[\w.\-]+@([\w\-]+\.[a-z]{2,})", ct.email)
    if not m:
        issues.append(f"некорректная почта {ct.email}")
    elif m.group(1) != domain:
        issues.append(f"домен почты должен быть {domain}, по бренду")
    return issues


def check_sections(data: dict[str, Any]) -> list[str]:
    sections = data.get("sections", {})
    ctx = Ctx.from_card(data)
    issues = []
    for key, value in sections.items():
        aspect = registry.find(key)
        if aspect is None:
            issues.append(f"неизвестный раздел {key}")
            continue
        missing = [r for r in aspect.requires if r not in sections]
        if missing:
            issues.append(f"{aspect.title}: нужен раздел {', '.join(missing)}")
        blank = blank_paths(value)
        if blank:
            issues.append(f"{aspect.title}: пустые поля: {', '.join(blank[:8])}")
        found = aspect.issues(ctx, aspect.model.model_validate(value))
        issues += [f"{aspect.title}: {i}" for i in found]
    return issues


EMPLOYEES = re.compile(r"(\d{1,4})\s+(?:сотрудник\w*|человек|Mitarbeit\w*|Beschäftigt\w*|Menschen)", re.I)
FOUNDED = re.compile(r"(?:основа\w*|создан\w*|gegründet|Gründung)\D{0,25}?(\d{4})", re.I)


def check_shared_facts(data: dict[str, Any]) -> list[str]:
    #сверяем числа и город в текстах с фактами
    issues = []
    # у клиентов и кейсов свои города и годы, их не смотрим
    about = [data["history"], data["specialization"], data["value_proposition"], data["tagline"]]
    bios = [p["bio"] for p in data["people"]]

    for n in sorted({int(m.group(1)) for t in about for m in EMPLOYEES.finditer(t)}):
        if n != data["employee_count"]:
            issues.append(f"в тексте о компании {n} сотрудников, а по фактам {data['employee_count']}")
    for year in sorted({int(m.group(1)) for t in about + bios for m in FOUNDED.finditer(t)}):
        if year != data["founding_year"]:
            issues.append(f"в тексте основание в {year} году, а по фактам в {data['founding_year']}")

    cities = catalog.COUNTRIES.get(data["country"], {}).get("cities", {})
    own = data["contacts"]["city"]
    for city, info in cities.items():
        if city == own:
            continue
        pattern = re.compile(rf"\b(?:{re.escape(city)}|{info.get('aliases', re.escape(city))})", re.I)
        if any(pattern.search(t) for t in (data["history"], data["specialization"])):
            issues.append(f"в истории или специализации упомянут город {city}, а компания в {own}")
    return issues


def check_facts(company: Company, existing_brands: Iterable[str] = ()) -> list[str]:
    #для утверждения фактов, разделы не смотрим
    issues = check_content(company, existing_brands=existing_brands)
    issues += check_contacts(company.country, company.contacts, company.brand)
    return issues + check_shared_facts(company.model_dump())


def check_company(company: Company, existing_brands: Iterable[str] = ()) -> list[str]:
    return check_facts(company, existing_brands) + check_sections(company.model_dump())


# ---------- проверки готового сайта ----------

def page_text(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return norm(html.unescape(re.sub(r"<[^>]+>", " ", page)))


def check_site(
    orig: dict[str, Any], card: dict[str, Any], pages: dict[str, str], files: dict[str, bytes], lang: str
) -> dict[str, Any]:
    #orig это факты, card те же данные на языке сайта
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append(result(name, ok, detail))

    ct = orig["contacts"]
    expected = [p.file for p in registry.pages_for(orig.get("sections", {}))]
    texts = {n: page_text(h) for n, h in pages.items()}

    add("Созданы все страницы", set(pages) == set(expected) and all(len(h) > 500 for h in pages.values()))

    no_meta = [
        n
        for n, h in pages.items()
        if not (
            re.search(r"<title>[^<]{3,}</title>", h)
            and re.search(r'<meta name="description" content="[^"]{20,}"', h)
            and "<h1" in h
            and 'rel="icon"' in h
            and f'<html lang="{lang}"' in h
        )
    ]
    add("Заголовок, описание, favicon и язык на каждой странице", not no_meta, ", ".join(no_meta))

    no_nav = [n for n, h in pages.items() if any(f'href="{p}"' not in h for p in expected)]
    add("Навигация и подвал ведут на все страницы", not no_nav, ", ".join(no_nav))

    left = [n for n, t in texts.items() if BAD.search(t)]
    add("Нет незаменённых переменных и заглушек", not left, ", ".join(left))

    missing = []
    for n, t in texts.items():
        for label, val in (
            ("бренд", orig["brand"]),
            ("юр. лицо", orig["legal_name"]),
            ("телефон", ct["phone"]),
            ("e-mail", ct["email"]),
        ):
            if norm(val) not in t:
                missing.append(f"{n}: {label}")
    add("Бренд, юр. лицо, телефон и почта одинаковы на всех страницах", not missing, "; ".join(missing))

    note = catalog.COUNTRIES[orig["country"]]["offer_note"][lang]
    no_note = [n for n, t in texts.items() if norm(note) not in t]
    add("В подвале каждой страницы оговорка об оферте", not no_note, ", ".join(no_note))
    # и что сайт демонстрационный, фраза от страны не зависит, только от языка
    demo = builder.STRINGS[lang]["demo_note"]
    no_demo = [n for n, t in texts.items() if norm(demo) not in t]
    add("В подвале каждой страницы пометка о демонстрационных данных", not no_demo, ", ".join(no_demo))

    comp = texts.get("company.html", "")
    no_addr = [v for v in (ct["street"], ct["postal_code"], ct["city"]) if norm(v) not in comp]
    add("Адрес на странице контактов совпадает с карточкой", not no_addr, ", ".join(no_addr))

    no_names = [p["name"] for p in orig["people"] if norm(p["name"]) not in comp]
    add("Вся команда показана на сайте", not no_names, ", ".join(no_names))

    # фото может быть сгенерированным jpg или условным svg
    people = range(1, len(orig["people"]) + 1)
    have = [i for i in people if f"assets/team/p{i}.jpg" in files or f"assets/team/p{i}.svg" in files]
    shown = pages.get("company.html", "").count("assets/team/p")
    add(
        "У каждого сотрудника есть фото, не меньше пяти",
        len(have) >= 5 and len(have) == len(people) and shown >= len(people),
    )

    prod = texts.get("product.html", "")
    product = card["product"]
    parts = [f["question"] for f in card["faq"]] + product["process"] + [s["title"] for s in product["scenarios"]]
    no_parts = [s for s in parts if norm(s) not in prod]
    name_ok = norm(product["name"]) in prod
    add("Продукт: название, шаги, сценарии и все вопросы FAQ", name_ok and not no_parts, ", ".join(no_parts))

    home = texts.get("index.html", "")
    no_adv = [a for a in card["advantages"] if norm(a) not in home]
    # слоган на главной разрезан на две части, ищем обе
    tagline_ok = all(norm(part) in home for part in split_tagline(card["tagline"]) if part)
    add("Главная: предложение и все преимущества", tagline_ok and not no_adv, ", ".join(no_adv))

    for key in card.get("sections", {}):
        aspect = registry.find(key)
        if aspect is not None:
            checks += aspect.check_site(orig, card, texts)

    return {"ok": all(c["ok"] for c in checks), "checks": checks}
