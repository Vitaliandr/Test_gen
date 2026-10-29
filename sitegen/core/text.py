import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from typing import Any

_RU = dict(
    zip(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p",
         "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"],
        strict=True,
    )
)  # fmt: skip

#недозаменённые шаблоны: {{ x }}, {city}, [город], %s
BAD = re.compile(
    r"\{\{|\}\}|\{%|TODO|lorem ipsum|XXX|<[a-z/][^>]*>|\bundefined\b|\bnull\b|\bNone\b|Имя Фамилия|Max Mustermann"
    r"|\{\s*[a-zа-яё_][\w.]*\s*\}"
    r"|\[\s*(?:город|имя|фамилия|бренд|название|компания|продукт|телефон|адрес|год|city|name|brand|company|product|"
    r"phone|address|year|Stadt|Firma|Marke|Produkt)[^\]]{0,30}\]"
    r"|<\s*(?:город|имя|фамилия|бренд|название|компания|продукт|телефон|адрес)[^>]{0,30}>"
    r"|%[sd]\b|\$\{?[a-z_]{2,}\}?",
    re.I,
)

# у немецкой политики колонки действий нет, это норм
MAY_BE_EMPTY = {"actions"}


# «2.», «2)», «2.1», «§ 2» в начале заголовка
#только номер пункта с точкой или скобкой, «2024 год» и «30 дней» не трогаем
LEADING_NUMBER = re.compile(r"^\s*(?:§\s*\d+(?:\.\d+)*\.?|\d{1,2}(?:\.\d+)*[.)])\s+")


def strip_number(text: str) -> str:
    #номер ставит шаблон, а модель иногда пишет свой, выходит «2. 2.»
    return LEADING_NUMBER.sub("", text)


# первое двоеточие или точка после хотя бы 20 символов
#после точки режем только перед заглавной, а то «т. е.» разрежет фразу
_TAGLINE_BREAK = re.compile(r"^(.{20,}?)(?::\s+|\.\s+(?=[A-ZА-ЯЁÄÖÜ]))(\S.*)$", re.S)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZА-ЯЁÄÖÜ])")


def split_tagline(text: str) -> tuple[str, str]:
    # длинный слоган режем на заголовок и подзаголовок
    m = _TAGLINE_BREAK.match(text.strip())
    if not m:
        return text, ""
    tail = m.group(2).rstrip(".")
    return m.group(1), tail[:1].upper() + tail[1:]


def sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text.strip()) if s]


def slugify(text: str, limit: int = 30) -> str:
    text = "".join(_RU.get(ch, ch) for ch in text.lower())
    text = text.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:limit].strip("-") or "firma"


def walk_strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v)


def blank_paths(obj: Any, path: str = "") -> list[str]:
    #пустые строки и строки из пробелов, в списках тоже
    if isinstance(obj, str):
        return [] if obj.strip() else [path or "значение"]
    out: list[str] = []
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key not in MAY_BE_EMPTY:
                out += blank_paths(val, f"{path}.{key}" if path else str(key))
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            out += blank_paths(val, f"{path}[{i}]")
    return out


def norm(s: str) -> str:
    return " ".join(s.split())


def fingerprint(obj: Any) -> str:
    # порядок ключей не влияет
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
