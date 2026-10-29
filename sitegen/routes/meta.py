from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from sitegen import catalog
from sitegen.api_models import ConfigOut, JobOut, ModelOut, ModelsOut
from sitegen.aspects import registry
from sitegen.background import jobs
from sitegen.clients import openrouter
from sitegen.core import builder, companies
from sitegen.database import get_session
from sitegen.errors import NotFound
from sitegen.settings import settings

router = APIRouter(prefix="/api", tags=["meta"])


@router.get("/config", response_model=ConfigOut)
def get_config() -> ConfigOut:
    # ключ наружу не отдаём, только факт что он есть
    return ConfigOut(
        has_key=settings.has_key(),
        key_source=settings.key_source(),
        default_model=settings.default_model,
        default_image_model=settings.default_image_model,
        themes=[{"key": k, "label": v["label"]} for k, v in builder.THEMES.items()],
        max_cost_usd=settings.max_cost_usd,
        max_cost_cap_usd=settings.max_cost_cap_usd,
        cost_presets=sorted({*catalog.COST_PRESETS, settings.max_cost_usd}),
        catalog=catalog.public_catalog(),
        schemes=[{"key": k, "label": v["label"]} for k, v in builder.SCHEMES.items()],
        fonts=[{"key": k, "label": v["label"]} for k, v in builder.FONTS.items()],
        aspects=[
            {"key": a.key, "number": a.number, "title": a.title, "requires": list(a.requires)}
            for a in registry.all_aspects()
        ],
        labels=registry.labels(),
    )


def _per_million(value: float | None) -> float | None:
    return None if value is None else round(value * 1_000_000, 4)


@router.get("/models", response_model=ModelsOut)
def get_models() -> ModelsOut:
    #каталог публичный, без ключа
    known = {m["id"]: m for m in openrouter.list_models()}
    presets = list(catalog.MODEL_PRESETS)
    ids = {p["id"] for p in presets}
    # OPENROUTER_MODELS тоже показываем, если их нет в списке
    presets += [{"id": m, "label": m, "note": "из настроек"} for m in settings.models() if m not in ids]
    if settings.default_model not in {p["id"] for p in presets}:
        presets.insert(0, {"id": settings.default_model, "label": settings.default_model, "note": "по умолчанию"})
    out = []
    for p in presets:
        price = known.get(p["id"])
        out.append(
            ModelOut(
                id=p["id"],
                label=p["label"],
                note=p["note"],
                prompt_per_m=_per_million(price["prompt"]) if price else None,
                completion_per_m=_per_million(price["completion"]) if price else None,
            )
        )
    listed = {p.id for p in out}

    images = []
    for p in catalog.IMAGE_PRESETS:
        price = known.get(p["id"])
        per_image = round(price["image_output"] * catalog.IMAGE_TOKENS, 4) if price and price["image_output"] else None
        images.append(ModelOut(id=p["id"], label=p["label"], note=p["note"], prompt_per_m=None, completion_per_m=None,
                               per_image=per_image))  # fmt: skip
    image_ids = {p["id"] for p in catalog.IMAGE_PRESETS}
    return ModelsOut(
        presets=out,
        others=sorted(m for m in known if m not in listed),
        image_presets=images,
        image_others=sorted(m for m, v in known.items() if v.get("makes_images") and m not in image_ids),
    )


@router.get("/spend")
def get_spend(session: Session = Depends(get_session)) -> dict[str, float]:
    return companies.total_spend(session)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str) -> JobOut:
    job = jobs.get(job_id)
    if job is None:
        raise NotFound("Задача не найдена")
    return JobOut.of(job)
