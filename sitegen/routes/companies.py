import json
from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session, object_session

from sitegen.api_models import AspectIn, CompanyOut, GenerateIn, JobOut, PhotosIn, SectionsIn
from sitegen.aspects import registry
from sitegen.background import jobs
from sitegen.background.jobs import Job
from sitegen.clients.openrouter import ImageMaker, Llm, require_key
from sitegen.core import companies as service
from sitegen.core import photos, sites
from sitegen.core.text import slugify
from sitegen.database import SessionLocal, get_session
from sitegen.deps import image_dep, llm_dep
from sitegen.repositories import companies as repo
from sitegen.settings import settings
from sitegen.tables import Company

router = APIRouter(prefix="/api/companies", tags=["companies"])


def _out(company: Company) -> CompanyOut:
    out = CompanyOut.model_validate(company)
    out.code = service.public_code(company.id)
    out.status = service.current_status(company)
    out.issues = service.issues_of(company)
    out.state = service.state(company)
    session = object_session(company)
    if session is not None:
        out.spend = service.spend(session, company)
    return out


def _warn(job: Job, failed: list[str]) -> None:
    if failed:
        job.warning = "Не всё получилось: " + "; ".join(failed)
        job.warning += ". Разделы можно создать заново на странице компании."


@router.post("/generate", response_model=JobOut)
def generate(body: GenerateIn, llm: Llm = Depends(llm_dep)) -> JobOut:
    require_key()
    model = service.pick_model(body.model)
    limit = service.pick_limit(body.max_cost)
    requested = body.model_dump(exclude={"model", "max_cost"})
    service.check_request(requested)

    def work(job: Job) -> int:
        with SessionLocal() as session:
            return service.generate(session, llm, requested, model, job.budget, job.set_stage)

    return JobOut.of(jobs.start(work, limit))


@router.get("", response_model=list[CompanyOut])
def list_companies(session: Session = Depends(get_session)) -> list[CompanyOut]:
    out = []
    for company in repo.all_items(session):
        item = CompanyOut.model_validate(company)
        item.code = service.public_code(company.id)
        item.status = service.current_status(company)
        out.append(item)
    return out


@router.get("/{company_id}", response_model=CompanyOut)
def get_company(company_id: int, session: Session = Depends(get_session)) -> CompanyOut:
    return _out(service.get_or_404(session, company_id))


@router.put("/{company_id}", response_model=CompanyOut)
def update_company(
    company_id: int, body: dict[str, Any] = Body(...), session: Session = Depends(get_session)
) -> CompanyOut:
    return _out(service.update(session, company_id, body))


@router.post("/{company_id}/approve-facts", response_model=CompanyOut)
def approve_facts(company_id: int, session: Session = Depends(get_session)) -> CompanyOut:
    return _out(service.approve_facts(session, company_id))


@router.post("/{company_id}/sections", response_model=JobOut)
def generate_sections(
    company_id: int, body: SectionsIn, llm: Llm = Depends(llm_dep), session: Session = Depends(get_session)
) -> JobOut:
    service.get_or_404(session, company_id)
    for key in body.aspects or []:
        registry.get(key)
    keys = body.aspects if body.aspects is not None else [a.key for a in registry.all_aspects()]
    if not all(registry.get(k).by_code for k in keys):
        require_key()
    model = service.pick_model(body.model)
    limit = service.pick_limit(body.max_cost)

    def work(job: Job) -> int:
        with SessionLocal() as own_session:
            company_id_, failed = service.generate_sections(
                own_session, llm, company_id, body.aspects, model, job.budget, job.set_stage
            )
        _warn(job, failed)
        return company_id_

    return JobOut.of(jobs.start(work, limit))


@router.post("/{company_id}/review", response_model=JobOut)
def review_company(
    company_id: int, body: AspectIn, llm: Llm = Depends(llm_dep), session: Session = Depends(get_session)
) -> JobOut:
    service.get_or_404(session, company_id)
    require_key()
    model = service.pick_model(body.model)
    limit = service.pick_limit(body.max_cost)

    def work(job: Job) -> int:
        with SessionLocal() as own_session:
            return service.run_review(own_session, llm, company_id, model, job.budget, job.set_stage)

    return JobOut.of(jobs.start(work, limit))


@router.post("/{company_id}/photos", response_model=JobOut)
def generate_photos(
    company_id: int,
    body: PhotosIn,
    maker: ImageMaker = Depends(image_dep),
    session: Session = Depends(get_session),
) -> JobOut:
    service.get_or_404(session, company_id)
    require_key()
    model = service.pick_model(body.model or settings.default_image_model)
    limit = service.pick_limit(body.max_cost)

    def work(job: Job) -> int:
        with SessionLocal() as own_session:
            company_id_, failed = photos.generate_photos(
                own_session, maker, company_id, model, job.budget, job.set_stage, body.force, body.only
            )
        if failed:
            job.warning = "Не все фото получились: " + "; ".join(failed)
        return company_id_

    return JobOut.of(jobs.start(work, limit))


@router.get("/{company_id}/photos/{index}")
def get_photo(company_id: int, index: int, session: Session = Depends(get_session)) -> FileResponse:
    return FileResponse(photos.file_for(session, company_id, index), media_type="image/jpeg")


@router.post("/{company_id}/approve", response_model=CompanyOut)
def approve_company(company_id: int, session: Session = Depends(get_session)) -> CompanyOut:
    return _out(service.approve(session, company_id))


@router.post("/{company_id}/aspects/{key}", response_model=JobOut)
def generate_aspect(
    company_id: int,
    key: str,
    body: AspectIn,
    llm: Llm = Depends(llm_dep),
    session: Session = Depends(get_session),
) -> JobOut:
    service.get_or_404(session, company_id)
    # этот раздел собирает код, ключ не нужен
    if not registry.get(key).by_code:
        require_key()
    model = service.pick_model(body.model)
    limit = service.pick_limit(body.max_cost)

    def work(job: Job) -> int:
        with SessionLocal() as own_session:
            return service.generate_aspect(own_session, llm, company_id, key, model, job.budget, job.set_stage)

    return JobOut.of(jobs.start(work, limit))


@router.delete("/{company_id}/aspects/{key}", response_model=CompanyOut)
def remove_aspect(company_id: int, key: str, session: Session = Depends(get_session)) -> CompanyOut:
    return _out(service.remove_aspect(session, company_id, key))


@router.delete("/{company_id}", status_code=204)
def delete_company(company_id: int, session: Session = Depends(get_session)) -> Response:
    # вместе с версиями сайтов и фото команды
    sites.delete_company(session, company_id)
    return Response(status_code=204)


@router.get("/{company_id}/download")
def download_company(company_id: int, session: Session = Depends(get_session)) -> Response:
    company = service.get_or_404(session, company_id)
    text = json.dumps(company.data, ensure_ascii=False, indent=2)
    name = f"company-{company.id}-{slugify(company.brand)}.json"
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    return Response(text, media_type="application/json", headers=headers)
