from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from sitegen.api_models import JobOut, SiteIn, SiteOut
from sitegen.background import jobs
from sitegen.background.jobs import Job
from sitegen.clients.openrouter import Llm, require_key
from sitegen.core import companies
from sitegen.core import sites as service
from sitegen.core.text import slugify
from sitegen.database import SessionLocal, get_session
from sitegen.deps import llm_dep
from sitegen.repositories import sites as repo
from sitegen.tables import Site

router = APIRouter(prefix="/api/sites", tags=["sites"])
preview_router = APIRouter(tags=["preview"])


def _out(session: Session, site: Site) -> SiteOut:
    company = companies.get_or_404(session, site.company_id)
    return SiteOut(
        id=site.id,
        version=repo.version(session, site),
        code=companies.site_code(site.id),
        company_id=site.company_id,
        brand=company.brand,
        language=site.language,
        style=site.style,
        model=site.model,
        report=site.report,
        cost=site.cost,
        created_at=site.created_at,
        outdated=site.source != company.data,
    )


@router.post("", response_model=JobOut)
def create_site(body: SiteIn, llm: Llm = Depends(llm_dep), session: Session = Depends(get_session)) -> JobOut:
    company = companies.get_or_404(session, body.company_id)
    limit = companies.pick_limit(body.max_cost)
    #деньги нужны только на перевод
    if company.data["language"] != body.language:
        require_key()

    def work(job: Job) -> int:
        with SessionLocal() as own_session:
            return service.create(
                own_session, llm, body.company_id, body.language, body.scheme, body.font, body.model,
                job.budget, job.set_stage, body.theme,
            )  # fmt: skip

    return JobOut.of(jobs.start(work, limit))


@router.get("", response_model=list[SiteOut])
def list_sites(company_id: int | None = None, session: Session = Depends(get_session)) -> list[SiteOut]:
    return [_out(session, s) for s in repo.all_items(session, company_id)]


@router.get("/{site_id}", response_model=SiteOut)
def get_site(site_id: int, session: Session = Depends(get_session)) -> SiteOut:
    return _out(session, service.get_or_404_site(session, site_id))


@router.delete("/{site_id}", status_code=204)
def delete_site(site_id: int, session: Session = Depends(get_session)) -> Response:
    service.delete(session, site_id)
    return Response(status_code=204)


@router.get("/{site_id}/download")
def download_site(site_id: int, session: Session = Depends(get_session)) -> Response:
    site = service.get_or_404_site(session, site_id)
    brand = companies.get_or_404(session, site.company_id).brand
    name = f"site-{slugify(brand)}-{companies.site_code(site.id)}-{site.language}.zip"
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    return Response(service.make_zip(site.id), media_type="application/zip", headers=headers)


@preview_router.get("/preview/{site_id}")
def preview_root(site_id: int) -> RedirectResponse:
    #со слэшем, а то css не найдётся
    return RedirectResponse(f"/preview/{site_id}/")


@preview_router.get("/preview/{site_id}/{path:path}")
def preview(site_id: int, path: str) -> FileResponse:
    return FileResponse(service.file_path(site_id, path))
