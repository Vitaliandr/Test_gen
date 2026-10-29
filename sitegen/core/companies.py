import copy
import re
from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from sitegen import catalog
from sitegen.aspects import registry
from sitegen.aspects.base import Aspect
from sitegen.card import Company as Card
from sitegen.clients.openrouter import Budget, Llm
from sitegen.core import consistency, generator, review, sections, similarity
from sitegen.core.text import fingerprint
from sitegen.errors import AppError, CostLimit, NotFound
from sitegen.repositories import companies as repo
from sitegen.repositories import sites as sites_repo
from sitegen.settings import settings
from sitegen.tables import Company, utcnow

MODEL_RE = re.compile(r"^[\w.\-]+/[\w.\-:]+$")


def pick_model(model: str | None) -> str:
    model = (model or "").strip() or settings.default_model
    if not MODEL_RE.match(model):
        raise AppError("Название модели должно быть вида провайдер/модель, например openai/gpt-4o-mini")
    return model


def pick_limit(value: float | None) -> float:
    if value is None:
        return settings.max_cost_usd
    if not 0 < value <= settings.max_cost_cap_usd:
        raise AppError(f"Лимит на операцию должен быть больше $0 и не выше ${settings.max_cost_cap_usd:.2f}")
    return float(value)


def check_request(req: dict[str, Any]) -> None:
    options: dict[str, Mapping[str, Any]] = {
        "country": catalog.COUNTRIES,
        "direction": catalog.DIRECTIONS,
        "service_type": catalog.SERVICE_TYPES,
        "scale": catalog.SCALES,
    }
    for field, allowed in options.items():
        if req[field] != "random" and req[field] not in allowed:
            raise AppError(f"Неизвестное значение поля {field}: {req[field]}")
    for key in req.get("aspects") or []:
        registry.get(key)


def public_code(n: int, shift: int = 104729) -> int:
    #6 цифр вместо 1, 2, 3. множитель не делится на 2, 3 и 5, поэтому разные id не дадут один код
    return (n * 386731 + shift) % 900000 + 100000


def site_code(site_id: int) -> int:
    # у сайтов свой сдвиг, чтоб код сайта не совпадал с кодом компании
    return public_code(site_id, 571903)


def get_or_404(session: Session, company_id: int) -> Company:
    company = repo.get(session, company_id)
    if company is None:
        raise NotFound("Компания не найдена")
    return company


def parse_card(body: dict[str, Any]) -> Card:
    try:
        return Card.model_validate(body)
    except ValidationError as e:
        text = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())
        raise AppError(f"Карточка не прошла проверку: {text}") from None


def issues_of(company: Company) -> list[str]:
    #для панели, тут ошибки не кидаем
    try:
        return consistency.check_company(Card.model_validate(company.data))
    except ValidationError as e:
        return [f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()]


def checked_card(data: dict[str, Any], what: str, existing_brands: Iterable[str] = ()) -> Card:
    card = parse_card(data)
    issues = consistency.check_company(card, existing_brands)
    if issues:
        raise AppError(f"{what}: " + "; ".join(issues))
    return card


def _facts(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k != "sections"}


def facts_fp(data: dict[str, Any]) -> str:
    return fingerprint(_facts(data))


def state(company: Company) -> dict[str, Any]:
    meta = company.meta or {}
    current_facts = facts_fp(company.data)
    current_card = fingerprint(company.data)
    built = meta.get("sections_fp", {})
    review = meta.get("review")
    photos = meta.get("photos", {})
    facts_ok = meta.get("facts_fp") == current_facts
    return {
        "facts_approved": facts_ok,
        # разделы, созданные по другой версии фактов
        "stale_sections": [k for k in company.data.get("sections", {}) if built.get(k) != current_facts],
        "planned": company.params.get("planned_aspects"),
        "review": review,
        "review_current": review is not None and review.get("fp") == current_card,
        "approved": facts_ok and meta.get("approved_fp") == current_card,
        # ключ фото как в photo_key
        "photos": [fingerprint({"name": p["name"], "role": p["role"]}) in photos for p in company.data["people"]],
    }


def current_status(company: Company) -> str:
    #статус всегда по отпечаткам, колонка в базе так, для списка
    st = state(company)
    return "approved" if st["approved"] else "facts_approved" if st["facts_approved"] else "draft"


def _refresh(company: Company, **meta: Any) -> None:
    # руками не ставим, любая правка сама снимает утверждение
    if meta:
        company.meta = {**(company.meta or {}), **meta}
    company.status = current_status(company)
    company.updated_at = utcnow()


def _charge(session: Session, company: Company, amount: float) -> None:
    # деньги записываем, даже если раздел не получился
    session.refresh(company)
    company.cost += amount
    session.commit()


def _add_section(session: Session, company: Company, aspect: Aspect, model: str, llm: Llm, budget: Budget) -> None:
    session.refresh(company)
    if not state(company)["facts_approved"]:
        raise AppError("Сначала утвердите общие факты: разделы строятся только на утверждённых")
    base = copy.deepcopy(company.data)
    base.setdefault("sections", {}).pop(aspect.key, None)
    spent = budget.spent
    try:
        section = sections.generate_section(aspect, base, model, llm, budget)
    finally:
        _charge(session, company, budget.spent - spent)

    #пока ждали модель, карточку могли поменять, берём свежую
    if _facts(company.data) != _facts(base):
        raise AppError("Карточку изменили, пока создавался раздел, запустите его заново")
    data = copy.deepcopy(company.data)
    data.setdefault("sections", {})[aspect.key] = section
    final = checked_card(data, f"Раздел «{aspect.title}» не прошёл совместную проверку")
    company.data = final.model_dump()
    built = {**(company.meta or {}).get("sections_fp", {}), aspect.key: facts_fp(company.data)}
    _refresh(company, sections_fp=built)
    session.commit()


def generate(
    session: Session, llm: Llm, requested: dict[str, Any], model: str, budget: Budget, stage: generator.Stage
) -> int:
    # этап 1, только общие факты
    keys = requested.get("aspects")
    if keys is None:
        keys = [a.key for a in registry.all_aspects()]
    #порядок проверяем до того, как платить
    registry.order(keys)

    existing = [(c.brand, c.data) for c in repo.all_items(session)]
    card, params = generator.generate(requested, model, llm, budget, stage, existing)
    params["planned_aspects"] = keys
    company = Company(brand=card.brand, data=card.model_dump(), params=params, model=model, cost=budget.spent, meta={})
    _refresh(company)
    repo.add(session, company)
    session.commit()
    return company.id


def approve_facts(session: Session, company_id: int) -> Company:
    company = get_or_404(session, company_id)
    others = [(c.brand, c.data) for c in repo.all_items(session) if c.id != company_id]
    issues = consistency.check_facts(parse_card(company.data), [b for b, _ in others])
    # после ручной правки тоже не должна стать копией
    issues += similarity.compare(company.data, company.data["language"], others)
    if issues:
        raise AppError("Факты нельзя утвердить: " + "; ".join(issues))
    _refresh(company, facts_fp=facts_fp(company.data))
    session.commit()
    return company


def generate_sections(
    session: Session,
    llm: Llm,
    company_id: int,
    keys: list[str] | None,
    model: str,
    budget: Budget,
    stage: generator.Stage,
) -> tuple[int, list[str]]:
    #этап 2, недостающие и устаревшие разделы
    company = get_or_404(session, company_id)
    if not state(company)["facts_approved"]:
        raise AppError("Сначала утвердите общие факты")
    if keys is None:
        planned = company.params.get("planned_aspects")
        # пустой список значит «без разделов», а не «все»
        keys = planned if planned is not None else [a.key for a in registry.all_aspects()]
    # раздел по старым фактам считаем как отсутствующий
    present = set(company.data.get("sections", {})) - set(state(company)["stale_sections"])
    ordered = registry.order([k for k in keys if k not in present], present=present)

    failed: list[str] = []
    missing: set[str] = set()
    for aspect in ordered:
        need = [r for r in aspect.requires if r in missing]
        if need:
            failed.append(f"{aspect.title}: нет раздела {', '.join(need)}")
            missing.add(aspect.key)
            continue
        stage(f"Раздел: {aspect.title}")
        try:
            _add_section(session, company, aspect, model, llm, budget)
        except AppError as e:
            failed.append(f"{aspect.title}: {e.message}")
            missing.add(aspect.key)
            if isinstance(e, CostLimit):
                done = set(company.data.get("sections", {})) | missing
                failed += [f"{a.title}: пропущен, лимит расходов исчерпан" for a in ordered if a.key not in done]
                return company.id, failed

    if not failed:
        try:
            _review(session, company, model, llm, budget, stage)
        except AppError as e:
            failed.append(f"Совместная проверка: {e.message}")
    return company.id, failed


def generate_aspect(
    session: Session, llm: Llm, company_id: int, key: str, model: str, budget: Budget, stage: generator.Stage
) -> int:
    company = get_or_404(session, company_id)
    aspect = registry.get(key)
    present = {k for k in company.data.get("sections", {}) if k != key}
    registry.order([key], present=present)
    stage(f"Раздел: {aspect.title}")
    _add_section(session, company, aspect, model, llm, budget)
    return company.id


def _review(session: Session, company: Company, model: str, llm: Llm, budget: Budget, stage: generator.Stage) -> None:
    session.refresh(company)
    #что ловит код, правим сами, модели за это не платим
    issues = issues_of(company)
    if issues:
        raise AppError("Сначала исправьте найденное проверкой: " + "; ".join(issues))
    stage("Совместная проверка комплекта")
    base = copy.deepcopy(company.data)
    spent = budget.spent
    try:
        result = review.review_card(base, model, llm, budget)
    finally:
        _charge(session, company, budget.spent - spent)
    if company.data != base:
        raise AppError("Карточку изменили во время проверки, запустите её заново")
    _refresh(company, review=result)
    session.commit()


def run_review(
    session: Session, llm: Llm, company_id: int, model: str, budget: Budget, stage: generator.Stage
) -> int:
    company = get_or_404(session, company_id)
    _review(session, company, model, llm, budget, stage)
    return company.id


def remove_aspect(session: Session, company_id: int, key: str) -> Company:
    company = get_or_404(session, company_id)
    registry.get(key)
    data = copy.deepcopy(company.data)
    if key not in data.get("sections", {}):
        raise NotFound("Такого раздела в карточке нет")
    blocked = registry.dependents(key, data["sections"])
    if blocked:
        raise AppError(f"Раздел нужен другим разделам: {', '.join(blocked)}")
    del data["sections"][key]
    company.data = data
    _refresh(company)
    session.commit()
    return company


def update(session: Session, company_id: int, body: dict[str, Any]) -> Company:
    company = get_or_404(session, company_id)
    # бренд не должен совпадать с другой компанией
    others = [c.brand for c in repo.all_items(session) if c.id != company_id]
    card = checked_card(body, "Карточка не прошла проверку", others)
    company.data = card.model_dump()
    company.brand = card.brand
    _refresh(company)
    session.commit()
    return company


def approve(session: Session, company_id: int) -> Company:
    # этап 3, весь комплект
    company = get_or_404(session, company_id)
    st = state(company)
    if not st["facts_approved"]:
        raise AppError("Утвердить нельзя: сначала утвердите общие факты")
    if st["stale_sections"]:
        #проверки прошёл, но писался по старым фактам, не пускаем
        titles = ", ".join(registry.get(k).title for k in st["stale_sections"])
        raise AppError(f"Утвердить нельзя: разделы созданы по старым фактам, пересоздайте их: {titles}")
    issues = issues_of(company)
    if issues:
        raise AppError("Утвердить нельзя, карточка не прошла проверку: " + "; ".join(issues))
    if not st["review_current"]:
        raise AppError("Утвердить нельзя: запустите совместную проверку для текущей версии карточки")
    if not st["review"]["ok"]:
        raise AppError("Утвердить нельзя: совместная проверка нашла противоречия, исправьте их и проверьте заново")
    _refresh(company, approved_fp=fingerprint(company.data))
    session.commit()
    return company


def spend(session: Session, company: Company) -> dict[str, float]:
    on_sites = sum(s.cost for s in sites_repo.all_items(session, company.id))
    return {"company": company.cost, "sites": on_sites, "total": company.cost + on_sites}


def total_spend(session: Session) -> dict[str, float]:
    companies = sum(c.cost for c in repo.all_items(session))
    on_sites = sum(s.cost for s in sites_repo.all_items(session))
    return {"companies": companies, "sites": on_sites, "total": companies + on_sites}
