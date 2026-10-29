from typing import Any

from pydantic import BaseModel

from sitegen.aspects.base import Aspect, Ctx, facts_block
from sitegen.clients.openrouter import Budget, Llm
from sitegen.core.generator import LANG_NAMES

SYSTEM = """Ты готовишь тестовые данные: пишешь раздел сайта вымышленной B2B-компании.
Правила:
- всё выдумано, не называй реальные компании, банки, фонды, вузы и реальных людей
- раздел не противоречит утверждённым фактам и продукту, цифры и имена берёшь из фактов
- не обещай того, чего нет в описании продукта
- не пиши регистрационные номера, налоговые номера, сертификаты, ссылки и адреса сайтов
Верни только один JSON-объект, без markdown и пояснений."""


def build_prompt(aspect: Aspect, ctx: Ctx) -> list[dict[str, str]]:
    user = (
        f"РАЗДЕЛ: {aspect.key}\n{facts_block(ctx)}\n\n{aspect.prompt(ctx)}\n\n"
        f"Тексты пиши на {LANG_NAMES[ctx.language]} языке, имена людей и названия не переводи.\n\n{aspect.skeleton}"
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def generate_section(aspect: Aspect, data: dict[str, Any], model: str, llm: Llm, budget: Budget) -> dict[str, Any]:
    ctx = Ctx.from_card(data)

    def validate(raw: dict[str, Any]) -> BaseModel:
        obj = aspect.model.model_validate(raw)
        issues = aspect.issues(ctx, obj)
        if issues:
            raise ValueError("; ".join(issues))
        return obj

    if aspect.by_code:
        return validate(aspect.build(ctx)).model_dump()
    obj: BaseModel = llm(model, build_prompt(aspect, ctx), budget, validate=validate)
    return obj.model_dump()
