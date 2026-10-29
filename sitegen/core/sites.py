import io
import shutil
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from sitegen.background import jobs
from sitegen.card import Company as Card
from sitegen.clients.openrouter import Budget, Llm
from sitegen.core import builder, consistency, photos, translate
from sitegen.core.companies import current_status, get_or_404, pick_model
from sitegen.core.generator import Stage
from sitegen.errors import AppError, NotFound
from sitegen.repositories import companies as companies_repo
from sitegen.repositories import sites as repo
from sitegen.settings import settings
from sitegen.tables import Site


def site_dir(site_id: int) -> Path:
    return Path(settings.sites_dir) / str(site_id)


def create(
    session: Session,
    llm: Llm,
    company_id: int,
    language: str,
    scheme: str,
    font: str,
    model: str | None,
    budget: Budget,
    stage: Stage,
    theme: str = "classic",
) -> int:
    known = (scheme in builder.SCHEMES, font in builder.FONTS, language in builder.STRINGS, theme in builder.THEMES)
    if not all(known):
        raise AppError("Неизвестный язык или оформление")
    company = get_or_404(session, company_id)
    if current_status(company) != "approved":
        raise AppError("Сайт делается только из утверждённой карточки, сначала утвердите компанию")

    orig: dict[str, Any] = company.data
    model_name = pick_model(model)
    card = orig
    # переводим только если язык сайта другой
    if orig["language"] != language:
        card = translate.translate_card(orig, language, model_name, llm, budget, stage)
        stage("Проверка перевода")
        problems = consistency.check_company(Card.model_validate(card))
        if problems:
            raise AppError("Перевод не прошёл проверку: " + "; ".join(problems))

    stage("Сборка страниц")
    files = builder.render_site(orig, card, language, scheme, font, theme, photos.photo_files(company))

    stage("Проверка согласованности")
    pages = {name: data.decode("utf-8") for name, data in files.items() if name.endswith(".html")}
    report = consistency.check_site(orig, card, pages, files, language)
    if not report["ok"]:
        failed = "; ".join(c["name"] for c in report["checks"] if not c["ok"])
        raise AppError(f"Сайт не прошёл проверку: {failed}")

    site = Site(
        company_id=company.id,
        language=language,
        style={"theme": theme, "scheme": scheme, "font": font},
        model=model_name if card is not orig else None,
        source=orig,
        report=report,
        cost=budget.spent,
    )
    repo.add(session, site)
    session.flush()
    try:
        folder = site_dir(site.id)
        for rel, data in files.items():
            target = folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        session.commit()
    except Exception:
        session.rollback()
        shutil.rmtree(site_dir(site.id), ignore_errors=True)
        raise
    return site.id


def get_or_404_site(session: Session, site_id: int) -> Site:
    site = repo.get(session, site_id)
    if site is None:
        raise NotFound("Сайт не найден")
    return site


def _not_while_running() -> None:
    # задача потом допишет фото или раздел уже удалённой компании
    if jobs.busy():
        raise AppError("Сейчас идёт генерация, удалить можно, когда она закончится")


def delete(session: Session, site_id: int) -> None:
    site = get_or_404_site(session, site_id)
    _not_while_running()
    repo.delete(session, site)
    session.commit()
    # файлы после коммита, а то при ошибке базы останется запись без сайта
    shutil.rmtree(site_dir(site_id), ignore_errors=True)


def delete_company(session: Session, company_id: int) -> None:
    #тут, а не в companies: сайты и фото импортируют companies, был бы цикл
    company = get_or_404(session, company_id)
    _not_while_running()
    site_ids = [s.id for s in repo.all_items(session, company_id)]
    for site in repo.all_items(session, company_id):
        repo.delete(session, site)
    companies_repo.delete(session, company)
    session.commit()
    for site_id in site_ids:
        shutil.rmtree(site_dir(site_id), ignore_errors=True)
    photos.remove_all(company_id)


def file_path(site_id: int, rel: str) -> Path:
    root = site_dir(site_id).resolve()
    target = (root / (rel or "index.html")).resolve()
    # не даём выйти из папки сайта через ..
    if root not in target.parents or not target.is_file():
        raise NotFound("Файл не найден")
    return target


def make_zip(site_id: int) -> bytes:
    folder = site_dir(site_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(folder).as_posix())
    return buf.getvalue()
