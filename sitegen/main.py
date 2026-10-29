import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from sitegen import logs
from sitegen.errors import AppError
from sitegen.routes import companies, key, meta, sites
from sitegen.settings import settings

logs.setup(as_json=settings.log_json)
log = logging.getLogger("sitegen")

ROOT = Path(__file__).resolve().parent.parent
CallNext = Callable[[Request], Awaitable[Response]]


def run_migrations() -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    run_migrations()
    yield


#swagger в проде не нужен, DOCS=false
app = FastAPI(
    title="TestGen",
    lifespan=lifespan,
    docs_url="/docs" if settings.docs else None,
    redoc_url="/redoc" if settings.docs else None,
    openapi_url="/openapi.json" if settings.docs else None,
)

app.include_router(meta.router)
app.include_router(key.router)
app.include_router(companies.router)
app.include_router(sites.router)
app.include_router(sites.preview_router)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    log.info("отказ %s %s: %s", exc.status_code, request.url.path, exc.message)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.exception("необработанная ошибка на %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "внутренняя ошибка, попробуйте позже"})


FIELDS = {
    "brand": "Бренд",
    "language": "Язык",
    "company_id": "Компания",
    "model": "Модель",
    "key": "Ключ",
}


def _human_error(err: dict[str, Any]) -> str:
    last = str(err["loc"][-1]) if err["loc"] else "body"
    field = FIELDS.get(last, last)
    if err["type"] == "missing":
        return f"{field}: обязательное поле"
    if err["type"].endswith("_type") or err["type"].endswith("_parsing"):
        return f"{field}: неверный тип значения"
    return f"{field}: неверное значение"


#pydantic отвечает по-английски, переводим
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": "; ".join(_human_error(e) for e in exc.errors())})


@app.middleware("http")
async def no_stale_frontend(request: Request, call_next: CallNext) -> Response:
    response = await call_next(request)
    if request.method == "GET" and "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-cache"
    return response


# CSP: выполняется только наш app.js, в предпросмотре скриптов нет
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
#сайт в предпросмотре на том же адресе, что и api, поэтому скрипты ему запрещены совсем
PREVIEW_CSP = (
    "default-src 'none'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next: CallNext) -> Response:
    response = await call_next(request)
    h = response.headers
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "no-referrer"
    # swagger грузится с cdn, csp ему мешает
    if request.url.path.startswith("/preview/"):
        h["Content-Security-Policy"] = PREVIEW_CSP
    elif not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
        h["Content-Security-Policy"] = CSP
    return response


#чужой сайт не должен слать post за нас
@app.middleware("http")
async def same_origin_only(request: Request, call_next: CallNext) -> Response:
    origin = request.headers.get("origin")
    if origin and request.method not in ("GET", "HEAD", "OPTIONS"):
        if urlparse(origin).netloc != request.headers.get("host", ""):
            log.info("отказ: чужой origin %s", origin[:100])
            return JSONResponse(status_code=403, content={"detail": "запрос с чужого сайта"})
    return await call_next(request)


@app.middleware("http")
async def with_request_id(request: Request, call_next: CallNext) -> Response:
    rid = logs.new_request_id(request.headers.get("x-request-id"))
    token = logs.request_id.set(rid)
    try:
        response = await call_next(request)
    finally:
        logs.request_id.reset(token)
    response.headers["X-Request-ID"] = rid
    return response


hosts = [h.strip() for h in settings.allowed_hosts.split(",") if h.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# в конце, а то перекроет api
app.mount("/", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="web")
