import copy
import json
import re
from collections.abc import Sequence
from typing import Any

from sitegen.aspects import registry
from sitegen.clients.openrouter import Budget, Llm
from sitegen.core.generator import Stage

FROM_LANG = {"ru": "русского", "de": "немецкого"}
TO_LANG = {"ru": "русский", "de": "немецкий"}

#переводим только эти поля, имена и телефоны не трогаем
CORE_TRANSLATABLE = {
    "role", "bio", "tagline", "value_proposition", "advantages", "history", "specialization",
    "audience", "client_problem", "summary", "inputs", "process", "outputs", "limitations",
    "question", "answer", "title", "situation", "how_it_helps", "result",
}  # fmt: skip

Path = tuple[str | int, ...]


def translatable() -> set[str]:
    # поля разделов берём у аспектов
    return CORE_TRANSLATABLE | registry.translatable()


def collect(obj: Any, path: Path = (), keys: set[str] | None = None) -> dict[Path, str]:
    keys = translatable() if keys is None else keys
    out: dict[Path, str] = {}
    if isinstance(obj, dict):
        for key, val in obj.items():
            if isinstance(val, str) and key in keys and not val.strip():
                #пустое не переводим, на нём падает проверка длины
                continue
            if isinstance(val, str) and key in keys:
                out[(*path, key)] = val
            elif isinstance(val, list) and val and all(isinstance(v, str) for v in val):
                if key in keys:
                    for i, s in enumerate(val):
                        out[(*path, key, i)] = s
            else:
                out.update(collect(val, (*path, key), keys))
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            out.update(collect(val, (*path, i), keys))
    return out


def _key(path: Path) -> str:
    return "/".join(map(str, path))


def _group(path: Path) -> str:
    # по разделу на запрос, ответ короче и при ошибке дешевле
    return f"sections/{path[1]}" if path[0] == "sections" else "core"


def _label(group: str) -> str:
    if group == "core":
        return "основная карточка"
    aspect = registry.find(group.removeprefix("sections/"))
    return aspect.title if aspect else group


def proper_names(card: dict[str, Any]) -> list[str]:
    #это при переводе меняться не должно
    names = [card["brand"], card["legal_name"], card["product"]["name"], *(p["name"] for p in card["people"])]
    refs = card.get("sections", {}).get("references") or {}
    names += [c["name"] for c in refs.get("clients", [])]
    names += [t["author_name"] for t in refs.get("testimonials", [])]
    # длинные вперёд, а то «Ормета» найдётся внутри «Ормета Ландшафт»
    return sorted({n for n in names if len(n) >= 3}, key=len, reverse=True)


def _translate_group(
    source: dict[str, str], card_lang: str, target: str, model: str, llm: Llm, budget: Budget,
    names: Sequence[str] = (),
) -> dict[str, str]:
    def validate(data: dict[str, Any]) -> dict[str, str]:
        if set(data) != set(source):
            raise ValueError(f"набор ключей изменился: {sorted(set(data) ^ set(source))[:8]}")
        for k, text in data.items():
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"пустой перевод у {k}")
            #числа на месте и длина похожая
            if set(re.findall(r"\d+", source[k])) - set(re.findall(r"\d+", text)):
                raise ValueError(f"в переводе {k} пропали числа")
            if not 0.3 < len(text) / max(len(source[k]), 1) < 3.5:
                raise ValueError(f"перевод {k} сильно отличается по длине")
            # название из оригинала должно остаться как есть
            lost = [n for n in names if n in source[k] and n not in text]
            if lost:
                raise ValueError(f"в переводе {k} изменилось название: {', '.join(lost)}, оставь его как есть")
        return {k: str(v) for k, v in data.items()}

    prompt = [
        {"role": "system", "content": "Ты переводчик деловых текстов. Верни только JSON-объект без пояснений."},
        {
            "role": "user",
            "content": f"Переведи значения JSON с {FROM_LANG[card_lang]} на {TO_LANG[target]} язык. "
            "Ключи не меняй. Имена людей, названия брендов, организаций и продуктов, числа и годы оставь как есть. "
            "Ничего не добавляй и не убирай, факты менять нельзя.\n\n" + json.dumps(source, ensure_ascii=False),
        },
    ]
    translated: dict[str, str] = llm(model, prompt, budget, validate=validate, temperature=0.2, max_tokens=8000)
    return translated


def translate_card(
    card: dict[str, Any], target: str, model: str, llm: Llm, budget: Budget, stage: Stage
) -> dict[str, Any]:
    paths = collect(card)
    groups: dict[str, dict[str, str]] = {}
    for path, text in paths.items():
        groups.setdefault(_group(path), {})[_key(path)] = text

    names = proper_names(card)
    translated: dict[str, str] = {}
    for name, source in groups.items():
        stage(f"Перевод на {TO_LANG[target]} язык: {_label(name)}")
        translated |= _translate_group(source, card["language"], target, model, llm, budget, names)

    result = copy.deepcopy(card)
    for path in paths:
        node: Any = result
        for step in path[:-1]:
            node = node[step]
        node[path[-1]] = translated[_key(path)].strip()
    result["language"] = target
    return result
