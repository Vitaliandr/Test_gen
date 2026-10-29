import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from sitegen.clients.openrouter import Budget, Llm
from sitegen.core.text import fingerprint

SYSTEM = """Ты проверяющий редактор. Перед публикацией сайта ищешь фактические противоречия
внутри комплекта данных вымышленной компании.
Что считается противоречием:
- разные числа, сроки, даты, сроки хранения данных, размеры команды, цены в разных частях
- разные имена, должности, названия компании, продукта или города для одного и того же
- раздел обещает то, чего продукт по описанию не делает, или нарушает ограничения продукта
- кейсы, отзывы, условия или политика описывают процесс иначе, чем описание продукта
Что не считается противоречием: стиль, повторы, разная подробность, вымышленность данных.
Не выдумывай проблем: если части согласованы, верни пустой список.
Верни только JSON-объект без пояснений."""

SKELETON = """Формат ответа:
{"contradictions": [
  {"where": "какие части расходятся, например faq[1] и sections.legal.terms[1]",
   "problem": "в чём противоречие", "fix": "как исправить"}
]}"""


class Contradiction(BaseModel):
    where: str = Field(min_length=2, max_length=300)
    problem: str = Field(min_length=5, max_length=600)
    fix: str = Field(default="", max_length=600)


class ReviewAnswer(BaseModel):
    contradictions: list[Contradiction] = Field(max_length=20)


def build_prompt(card: dict[str, Any]) -> list[dict[str, str]]:
    #контакты собрал и проверил код, модели их не шлём
    shown = {k: v for k, v in card.items() if k != "contacts"}
    user = "Комплект данных компании:\n" + json.dumps(shown, ensure_ascii=False, indent=1) + "\n\n" + SKELETON
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def review_card(card: dict[str, Any], model: str, llm: Llm, budget: Budget) -> dict[str, Any]:
    # результат привязан к отпечатку, правка карточки его сбрасывает
    answer: ReviewAnswer = llm(
        model, build_prompt(card), budget, validate=ReviewAnswer.model_validate, temperature=0.0, max_tokens=3000
    )
    found = [c.model_dump() for c in answer.contradictions]
    return {
        "fp": fingerprint(card),
        "ok": not found,
        "contradictions": found,
        "model": model,
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
