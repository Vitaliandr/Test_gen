import hashlib
from html import escape
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, ChoiceLoader, Environment, FileSystemLoader, select_autoescape

from sitegen import catalog
from sitegen.aspects import registry
from sitegen.core.text import sentences, split_tagline, strip_number

TEMPLATES = Path(__file__).resolve().parent.parent / "templates" / "site"


def _make_env(loader: BaseLoader) -> Environment:
    made = Environment(loader=loader, autoescape=select_autoescape(["html"]))
    # у старых карточек номер прямо в заголовке, срезаем
    made.filters["unnumber"] = strip_number
    made.filters["split_tagline"] = split_tagline
    made.filters["sentences"] = sentences
    return made


env = _make_env(FileSystemLoader(TEMPLATES))

#тема это папка themes/<ключ>, чего в ней нет
# берётся из общих шаблонов
THEMES = {
    "classic": {"label": "Классический"},
    "editorial": {"label": "Журнальный"},
    "dark": {"label": "Тёмный"},
}
_theme_envs: dict[str, Environment] = {}


def env_for(theme: str) -> Environment:
    if theme == "classic":
        return env
    if theme not in _theme_envs:
        loader = ChoiceLoader([FileSystemLoader(TEMPLATES / "themes" / theme), FileSystemLoader(TEMPLATES)])
        _theme_envs[theme] = _make_env(loader)
    return _theme_envs[theme]

SCHEMES = {
    "ocean": {"label": "Океан", "primary": "#1f5fbf", "accent": "#0b7f7e", "bg": "#f6f9fc",
              "text": "#14202e", "muted": "#53647a", "dark": "#0f2744"},
    "graphite": {"label": "Графит", "primary": "#374151", "accent": "#b45309", "bg": "#f5f5f4",
                 "text": "#1c1917", "muted": "#57534e", "dark": "#1f2937"},
    "forest": {"label": "Лес", "primary": "#1f7a4d", "accent": "#a16207", "bg": "#f4f8f5",
               "text": "#13261b", "muted": "#4f6358", "dark": "#10321f"},
    "violet": {"label": "Фиолетовый", "primary": "#5b3fd0", "accent": "#be185d", "bg": "#f8f7fd",
               "text": "#1b1633", "muted": "#5c5676", "dark": "#251b52"},
}  # fmt: skip

SANS = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
FONTS = {
    # текст всегда без засечек, меняются только заголовки
    "sans": {"label": "Современный, без засечек", "body": SANS, "heading": SANS},
    "serif": {"label": "Классический, с засечками", "body": SANS, "heading": "Georgia, 'Times New Roman', serif"},
}

#строки основных страниц, у аспектов свои
STRINGS = {
    "ru": {
        "demo_note": "Сайт создан для демонстрации. Компания, люди и реквизиты вымышлены, информация носит "
                     "исключительно ознакомительный характер.",
        "cta_product": "Узнать о продукте", "audience": "Для кого мы работаем",
        "problem": "Какую задачу мы решаем", "advantages": "Преимущества",
        "process": "Как это работает", "inputs": "Входные данные", "outputs": "Результат",
        "limitations": "Ограничения", "faq": "Частые вопросы", "history": "История компании",
        "specialization": "Специализация", "team": "Команда", "contacts": "Контакты",
        "address": "Адрес", "phone": "Телефон", "email": "E-mail",
        "no_form": "Формы обратной связи на сайте нет, напишите на почту или позвоните.",
        "about_product": "О продукте", "scenarios": "Сценарии использования", "situation": "Ситуация",
        "how_it_helps": "Как помогает продукт", "outcome": "Что получает клиент",
    },
    "de": {
        "demo_note": "Diese Website dient nur zur Demonstration. Unternehmen, Personen und Angaben sind fiktiv.",
        "cta_product": "Produkt kennenlernen", "audience": "Für wen wir arbeiten",
        "problem": "Welches Problem wir lösen", "advantages": "Vorteile",
        "process": "So funktioniert es", "inputs": "Eingangsdaten", "outputs": "Ergebnis",
        "limitations": "Einschränkungen", "faq": "Häufige Fragen", "history": "Unternehmensgeschichte",
        "specialization": "Spezialisierung", "team": "Team", "contacts": "Kontakt",
        "address": "Adresse", "phone": "Telefon", "email": "E-Mail",
        "no_form": "Ein Kontaktformular gibt es hier nicht, schreiben Sie uns eine E-Mail oder rufen Sie an.",
        "about_product": "Zum Produkt", "scenarios": "Anwendungsszenarien", "situation": "Ausgangslage",
        "how_it_helps": "So hilft das Produkt", "outcome": "Was der Kunde erhält",
    },
}  # fmt: skip


def avatar_svg(name: str) -> bytes:
    # цвет от имени, чтоб у каждого был свой
    hue = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16) % 360
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" role="img" aria-label="{escape(name)}">'
        f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="hsl({hue},45%,42%)"/>'
        f'<stop offset="1" stop-color="hsl({(hue + 50) % 360},50%,32%)"/></linearGradient></defs>'
        f'<rect width="120" height="120" fill="url(#g)"/>'
        f'<circle cx="60" cy="46" r="20" fill="rgba(255,255,255,.85)"/>'
        f'<path d="M20 120c0-26 18-42 40-42s40 16 40 42z" fill="rgba(255,255,255,.85)"/></svg>'
    )
    return svg.encode("utf-8")


def favicon_svg(brand: str, color: str) -> bytes:
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        f'<rect width="64" height="64" rx="14" fill="{color}"/>'
        f'<text x="32" y="44" font-family="Arial, sans-serif" font-size="36" font-weight="700" '
        f'text-anchor="middle" fill="#fff">{escape(brand[:1].upper())}</text></svg>'
    )
    return svg.encode("utf-8")


def render_site(
    orig: dict[str, Any],
    card: dict[str, Any],
    lang: str,
    scheme: str,
    font: str,
    theme: str = "classic",
    photos: list[bytes | None] | None = None,
) -> dict[str, bytes]:
    # orig это факты, card то же самое на языке сайта
    colors = SCHEMES[scheme]
    jinja = env_for(theme)

    #фото нет, ставим силуэт
    files: dict[str, bytes] = {}
    team_photos = []
    for i, person in enumerate(card["people"], 1):
        jpeg = photos[i - 1] if photos and i <= len(photos) else None
        path = f"assets/team/p{i}.jpg" if jpeg else f"assets/team/p{i}.svg"
        files[path] = jpeg if jpeg else avatar_svg(person["name"])
        team_photos.append(path)
    t = STRINGS[lang]
    ct = orig["contacts"]
    sections = card.get("sections", {})
    pages = registry.pages_for(orig.get("sections", {}))
    facts = {
        "brand": orig["brand"],
        "legal_name": orig["legal_name"],
        "phone": ct["phone"],
        "phone_raw": "+" + "".join(ch for ch in ct["phone"] if ch.isdigit()),
        "email": ct["email"],
        "street": ct["street"],
        "postal_code": ct["postal_code"],
        "city": ct["city"],
        "country": catalog.country_name(orig["country"], lang),
        "country_code": orig["country"],
        "offer_note": catalog.COUNTRIES[orig["country"]]["offer_note"][lang],
    }
    menu = [{"file": p.file, "title": p.titles[lang]} for p in pages if p.placement == "nav"]
    footer = [{"file": p.file, "title": p.titles[lang]} for p in pages if p.placement == "footer"]

    for p in pages:
        aspect = registry.find(p.aspect) if p.aspect else None
        if aspect is not None:
            section = sections[aspect.key]
            description = aspect.meta(section, facts) or f"{p.titles[lang]}. {orig['legal_name']}"
            title = f"{p.titles[lang]} | {orig['brand']}"
        else:
            section = None
            description = {
                "index": f"{card['tagline']}. {card['value_proposition']}",
                "product": card["product"]["summary"],
                "company": f"{orig['legal_name']}, {ct['city']}. {card['specialization']}",
            }[p.key]
            title = f"{p.titles[lang]} | {orig['brand']}"
            if p.key == "index":
                title = f"{orig['brand']} | {card['tagline']}"
        page = jinja.get_template(p.file).render(
            c=card, facts=facts, t=t, ta=aspect.strings.get(lang, {}) if aspect else {}, section=section,
            lang=lang, menu=menu, footer=footer, page=p, ptitle=p.titles[lang], photos=team_photos,
            page_title=title, description=description[:200],
        )  # fmt: skip
        files[p.file] = page.encode("utf-8")

    css = jinja.get_template("style.css.j2").render(colors=colors, fonts=FONTS[font])
    files["assets/style.css"] = css.encode("utf-8")
    files["favicon.svg"] = favicon_svg(orig["brand"], colors["primary"])
    return files
