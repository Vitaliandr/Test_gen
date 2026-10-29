import re
from collections.abc import Iterable
from typing import Any

# по ТЗ компании должны отличаться вот этим
FIELDS = {
    "history": "история",
    "specialization": "специализация",
    "value_proposition": "предложение компании",
    "team": "биографии команды",
    "product": "описание продукта",
    "faq": "вопросы и ответы",
}

#пороги подбирал по уже созданным: у разных слов до 0.3, фраз до 0.05,
# а у пересказа 0.9 и 0.8
WORDS_LIMIT = 0.45
PHRASES_LIMIT = 0.15

_WORD = re.compile(r"[a-zа-яёäöüß]+")
_STOP = set(
    "и в во на с со по для не что как это его её их а но или к ко от до из у же ли бы за о об при так "
    "und der die das den dem des ein eine einen mit von zu im in ist sind für auf als auch nicht wie bei aus".split()
)


def stems(text: str) -> list[str]:
    # первые 6 букв, чтоб «компании» и «компанией» совпали
    return [w[:6] for w in _WORD.findall(text.lower()) if len(w) > 2 and w not in _STOP]


def _jaccard(a: set[Any], b: set[Any]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def scores(a: str, b: str) -> tuple[float, float]:
    #общие слова + общие тройки слов подряд, тройки ловят переписанное
    sa, sb = stems(a), stems(b)
    phrases_a = {tuple(sa[i : i + 3]) for i in range(len(sa) - 2)}
    phrases_b = {tuple(sb[i : i + 3]) for i in range(len(sb) - 2)}
    return _jaccard(set(sa), set(sb)), _jaccard(phrases_a, phrases_b)


def _names(card: dict[str, Any]) -> list[str]:
    out = [card.get("brand", ""), card.get("legal_name", ""), (card.get("product") or {}).get("name", "")]
    for p in card.get("people", []):
        out += p["name"].split()
    return sorted({n for n in out if len(n) > 2}, key=len, reverse=True)


def texts_of(card: dict[str, Any]) -> dict[str, str]:
    # имена убираем, а то копия с другими именами пройдёт
    p = card.get("product") or {}
    raw = {
        "history": card.get("history", ""),
        "specialization": card.get("specialization", ""),
        "value_proposition": card.get("value_proposition", ""),
        "team": " ".join(x.get("bio", "") for x in card.get("people", [])),
        "product": " ".join([p.get("summary", ""), *[s for k in ("inputs", "process", "outputs", "limitations")
                                                    for s in p.get(k, [])]]),
        "faq": " ".join(f"{q['question']} {q['answer']}" for q in card.get("faq", [])),
    }
    names = _names(card)
    for key, text in raw.items():
        for n in names:
            text = re.sub(re.escape(n), " ", text, flags=re.I)
        raw[key] = text
    return raw


def compare(card: dict[str, Any], language: str, others: Iterable[tuple[str, dict[str, Any]]]) -> list[str]:
    issues = []
    mine = texts_of(card)
    for brand, other in others:
        #на разных языках сравнивать бесполезно
        if other.get("language") != language:
            continue
        theirs = texts_of(other)
        for key, label in FIELDS.items():
            words, phrases = scores(mine[key], theirs[key])
            if words >= WORDS_LIMIT or phrases >= PHRASES_LIMIT:
                issues.append(
                    f"поле «{label}» слишком похоже на компанию {brand} (общих слов {words:.0%}, фраз {phrases:.0%}), "
                    "придумай другой сюжет и перескажи своими словами"
                )
    return issues
