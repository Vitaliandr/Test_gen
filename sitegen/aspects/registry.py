from collections.abc import Iterable

from sitegen.aspects.base import Aspect, Page
from sitegen.errors import AppError

_aspects: dict[str, Aspect] = {}

INDEX = Page("index", "index.html", {"ru": "Главная", "de": "Startseite"})
PRODUCT = Page("product", "product.html", {"ru": "Продукт", "de": "Produkt"})
COMPANY = Page("company", "company.html", {"ru": "Компания и контакты", "de": "Unternehmen & Kontakt"})


def register(aspect: Aspect) -> None:
    if aspect.key in _aspects:
        raise ValueError(f"аспект {aspect.key} уже зарегистрирован")
    _aspects[aspect.key] = aspect


def unregister(key: str) -> None:
    _aspects.pop(key, None)


def find(key: str) -> Aspect | None:
    return _aspects.get(key)


def get(key: str) -> Aspect:
    aspect = _aspects.get(key)
    if aspect is None:
        raise AppError(f"Неизвестный раздел: {key}")
    return aspect


def all_aspects() -> list[Aspect]:
    return list(_aspects.values())


def order(keys: Iterable[str], present: Iterable[str] = ()) -> list[Aspect]:
    # сначала то, от чего зависят другие
    chosen = [get(k) for k in dict.fromkeys(keys)]
    have = set(present)
    ready: list[Aspect] = []
    waiting = list(chosen)
    while waiting:
        step = [a for a in waiting if all(r in have or r in {x.key for x in ready} for r in a.requires)]
        if not step:
            a = waiting[0]
            need = [r for r in a.requires if r not in have]
            raise AppError(f"Раздел «{a.title}» требует сначала создать: {', '.join(need)}")
        ready += step
        waiting = [a for a in waiting if a not in step]
    return ready


def dependents(key: str, present: Iterable[str]) -> list[str]:
    here = set(present)
    return [a.key for a in _aspects.values() if key in a.requires and a.key in here]


def translatable() -> set[str]:
    out: set[str] = set()
    for a in _aspects.values():
        out |= a.translatable
    return out


def labels() -> dict[str, str]:
    out: dict[str, str] = {}
    for a in _aspects.values():
        out.update(a.labels)
    return out


def pages_for(section_keys: Iterable[str]) -> list[Page]:
    #3 основные + страницы тех разделов, что есть
    here = set(section_keys)
    extra = [p for a in _aspects.values() if a.key in here for p in a.pages]
    nav = [p for p in extra if p.placement == "nav"]
    footer = [p for p in extra if p.placement == "footer"]
    return [INDEX, PRODUCT, *nav, COMPANY, *footer]
