import io
import random
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from sitegen import catalog
from sitegen.clients import openrouter
from sitegen.clients.openrouter import Budget, ImageMaker
from sitegen.core.companies import get_or_404, state
from sitegen.core.generator import Stage
from sitegen.core.text import fingerprint
from sitegen.errors import AppError, CostLimit, NotFound
from sitegen.settings import settings
from sitegen.tables import Company

SIZE = 512

PROMPT = (
    "Photorealistic professional portrait of a fictional person who does not exist "
    "and does not resemble any real or famous person. "
    "Name for context: {name}. Job title: {role}. Works at a small B2B analytics company in {country}. "
    "Head and shoulders, {pose}, {expression}, wearing {clothing}. "
    "Background: {background}. Lighting: {light}. Square format. No text, no logos, no watermark."
)

# без вариантов вся команда как с одной фотосессии
#одежда нейтральная, подойдёт любому
CLOTHING = {
    "ceo": [
        "a dark suit without a tie", "a navy blazer over an open-collar shirt",
        "a charcoal blazer over a fine knit top", "a light grey suit with a white shirt",
    ],
    "head": [
        "a blazer over a crew-neck top", "a light blue shirt without a jacket",
        "a dark knit sweater over a collared shirt", "a camel blazer over a black top", "a white shirt and a dark vest",
    ],
    "staff": [
        "a smart casual shirt with rolled sleeves", "a simple knitted sweater", "a dark turtleneck",
        "a denim shirt", "a light linen shirt", "a casual blazer over a t-shirt",
    ],
}
BACKGROUNDS = [
    "a softly blurred modern office", "a plain warm beige wall", "a bright window with blurred daylight",
    "a dark charcoal studio backdrop", "a blurred bookshelf", "a light concrete wall", "blurred green office plants",
]
POSES = [
    "facing the camera", "body turned slightly to the left, looking at the camera",
    "body turned slightly to the right, looking at the camera", "leaning slightly forward", "arms loosely crossed",
]
EXPRESSIONS = [
    "a warm smile", "a calm confident look", "a slight thoughtful smile", "a friendly open smile",
    "a relaxed neutral expression",
]
LIGHTS = ["soft natural window light", "soft studio light", "warm late-afternoon light", "even overcast daylight"]


def photo_key(person: dict[str, Any]) -> str:
    # фото по имени и должности, правка bio его не сбрасывает
    return fingerprint({"name": person["name"], "role": person["role"]})


def _shuffled(items: list[str], seed: str) -> list[str]:
    out = list(items)
    random.Random(seed).shuffle(out)
    return out


def look_for(person: dict[str, Any], card: dict[str, Any]) -> dict[str, str]:
    #варианты мешаем один раз на компанию, так у соседей не совпадают
    seed = fingerprint({"brand": card["brand"], "legal_name": card["legal_name"]})
    keys = [photo_key(p) for p in card["people"]]
    n = keys.index(photo_key(person)) if photo_key(person) in keys else 0
    level = person.get("level", "staff")
    same_level = [photo_key(p) for p in card["people"] if p.get("level", "staff") == level]
    k = same_level.index(photo_key(person)) if photo_key(person) in same_level else 0

    def pick(items: list[str], name: str, i: int) -> str:
        return _shuffled(items, seed + name)[i % len(items)]

    return {
        "clothing": pick(CLOTHING.get(level, CLOTHING["staff"]), "clothing" + level, k),
        "background": pick(BACKGROUNDS, "background", n),
        "pose": pick(POSES, "pose", n),
        "expression": pick(EXPRESSIONS, "expression", n),
        "light": pick(LIGHTS, "light", n),
    }


def prompt_for(person: dict[str, Any], card: dict[str, Any]) -> str:
    country = catalog.COUNTRIES.get(card["country"], {}).get("name_en", card["country"])
    return PROMPT.format(name=person["name"], role=person["role"], country=country, **look_for(person, card))


def process(raw: bytes) -> bytes:
    # больше 512 сайту не надо, архив не раздуваем
    try:
        source = Image.open(io.BytesIO(raw))
        source.load()
    except (UnidentifiedImageError, OSError):
        raise AppError("модель вернула не картинку") from None
    rgb = (ImageOps.exif_transpose(source) or source).convert("RGB")
    # чуть выше центра, чтоб не резать голову
    square = ImageOps.fit(rgb, (SIZE, SIZE), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    buf = io.BytesIO()
    square.save(buf, "JPEG", quality=85, optimize=True)
    return buf.getvalue()


def catalog_price(model: str) -> float | None:
    #сколько стоит одна картинка, если тариф известен
    for item in openrouter.list_models():
        if item["id"] == model and item["image_output"]:
            return float(item["image_output"]) * catalog.IMAGE_TOKENS
    return None


def _folder(company_id: int) -> Path:
    return Path(settings.media_dir) / str(company_id)


def remove_all(company_id: int) -> None:
    shutil.rmtree(_folder(company_id), ignore_errors=True)


def photo_path(company: Company, person: dict[str, Any]) -> Path | None:
    name = (company.meta or {}).get("photos", {}).get(photo_key(person))
    if not name:
        return None
    path = _folder(company.id) / name
    return path if path.is_file() else None


def photo_files(company: Company) -> list[bytes | None]:
    # в порядке команды, None где фото нет
    out: list[bytes | None] = []
    for person in company.data["people"]:
        path = photo_path(company, person)
        out.append(path.read_bytes() if path else None)
    return out


def file_for(session: Session, company_id: int, index: int) -> Path:
    company = get_or_404(session, company_id)
    people = company.data["people"]
    if not 0 <= index < len(people):
        raise NotFound("Нет такого сотрудника")
    path = photo_path(company, people[index])
    if path is None:
        raise NotFound("Фото пока нет")
    return path


def _save(session: Session, company: Company, cost: float, key: str | None = None, name: str | None = None) -> None:
    # пока рисовали, карточку могли поменять
    session.refresh(company)
    company.cost += cost
    if key and name:
        meta = company.meta or {}
        company.meta = {**meta, "photos": {**meta.get("photos", {}), key: name}}
    session.commit()


def generate_photos(
    session: Session,
    maker: ImageMaker,
    company_id: int,
    model: str,
    budget: Budget,
    stage: Stage,
    force: bool = False,
    only: int | None = None,
) -> tuple[int, list[str]]:
    company = get_or_404(session, company_id)
    if not state(company)["facts_approved"]:
        raise AppError("Сначала утвердите общие факты: фото делаются по утверждённой команде")
    people = list(company.data["people"])
    if only is not None:
        if not 0 <= only < len(people):
            raise NotFound("Нет такого сотрудника")
        #одного человека рисуем всегда, даже если фото есть
        force = True
    folder = _folder(company.id)
    folder.mkdir(parents=True, exist_ok=True)

    failed: list[str] = []
    # одна картинка может перешагнуть лимит,
    #поэтому заранее смотрим, хватит ли ещё на одну
    expected = catalog_price(model)
    for n, person in enumerate(people):
        if only is not None and n != only:
            continue
        if not force and photo_path(company, person):
            continue
        if expected and budget.spent + expected > budget.limit:
            left = [p["name"] for i, p in enumerate(people) if i >= n and (only is None or i == only)
                    and (force or not photo_path(company, p))]
            reason = f"пропущено, до лимита не хватает на ещё одно фото (примерно ${expected:.3f})"
            failed += [f"{name}: {reason}" for name in left]
            break
        stage(f"Фото {n + 1} из {len(people)}: {person['name']}")
        spent = budget.spent
        try:
            jpeg = process(maker(model, prompt_for(person, company.data), budget))
        except AppError as e:
            _save(session, company, budget.spent - spent)
            failed.append(f"{person['name']}: {e.message}")
            if isinstance(e, CostLimit):
                failed += [f"{p['name']}: пропущено, лимит расходов исчерпан" for p in people[n + 1 :]]
                break
            continue
        expected = max(expected or 0.0, budget.spent - spent)
        key = photo_key(person)
        name = f"{key}.jpg"
        (folder / name).write_bytes(jpeg)
        _save(session, company, budget.spent - spent, key, name)
    return company.id, failed
