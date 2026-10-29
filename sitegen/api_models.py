from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field, SecretStr

from sitegen.background.jobs import Job


def _as_utc(value: datetime) -> datetime:
    #sqlite теряет tz, а у нас всегда UTC
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]


class GenerateIn(BaseModel):
    brand: str = Field("", max_length=60)
    country: str = "DE"
    direction: str = "random"
    service_type: str = "random"
    scale: str = "random"
    language: Literal["ru", "de"] = "ru"
    model: str = ""
    # None = все разделы, [] = без разделов
    aspects: list[str] | None = None
    #не прислали, берём MAX_COST_USD
    max_cost: float | None = None


class AspectIn(BaseModel):
    model: str = ""
    max_cost: float | None = None


class SectionsIn(AspectIn):
    # None = те, что выбрали при создании
    aspects: list[str] | None = None


class PhotosIn(AspectIn):
    #всех заново, иначе только без фото
    force: bool = False
    # перерисовать одного, номер с 0
    only: int | None = None


class SiteIn(BaseModel):
    company_id: int
    language: Literal["ru", "de"]
    theme: str = "classic"
    scheme: str = "ocean"
    font: str = "sans"
    model: str = ""
    max_cost: float | None = None


class JobOut(BaseModel):
    id: str
    status: str
    stage: str
    error: str | None
    warning: str | None
    result_id: int | None
    cost: float
    cost_known: bool
    limit: float

    @classmethod
    def of(cls, job: Job) -> "JobOut":
        return cls(
            id=job.id,
            status=job.status,
            stage=job.stage,
            error=job.error,
            warning=job.warning,
            result_id=job.result_id,
            cost=job.budget.spent,
            cost_known=job.budget.known,
            limit=job.budget.limit,
        )


class CompanyOut(BaseModel):
    id: int
    # то, что видит пользователь, id остаётся для ссылок
    code: int = 0
    brand: str
    status: str
    data: dict[str, Any]
    params: dict[str, Any]
    model: str | None
    cost: float
    created_at: UtcDatetime
    updated_at: UtcDatetime
    #что сейчас мешает утвердить
    issues: list[str] = []
    # считается по текущей версии карточки
    state: dict[str, Any] = {}
    #переводы сайтов тоже сюда
    spend: dict[str, float] = {}

    model_config = {"from_attributes": True}


class SiteOut(BaseModel):
    id: int
    # у каждой компании свой счёт, с 1
    version: int
    # шестизначный id для панели, как у компаний
    code: int
    company_id: int
    brand: str
    language: str
    style: dict[str, Any]
    model: str | None
    report: dict[str, Any]
    cost: float
    created_at: UtcDatetime
    #карточку правили уже после сборки
    outdated: bool


class KeyIn(BaseModel):
    # SecretStr, а то при 422 ключ вылезет в ответе
    key: SecretStr


class KeyOut(BaseModel):
    has_key: bool
    source: str
    hint: str
    editable: bool
    note: str
    checked: bool | None = None
    limit: float | None = None
    usage: float | None = None


class ModelOut(BaseModel):
    id: str
    label: str
    note: str
    #за 1 млн токенов, None если каталог не ответил
    prompt_per_m: float | None
    completion_per_m: float | None
    # только у моделей картинок
    per_image: float | None = None


class ModelsOut(BaseModel):
    presets: list[ModelOut]
    #подсказки для поля «другая модель»
    others: list[str]
    image_presets: list[ModelOut] = []
    image_others: list[str] = []


class ConfigOut(BaseModel):
    has_key: bool
    # env, файл или хранилище, сам ключ не отдаём
    key_source: str
    default_model: str
    default_image_model: str
    themes: list[dict[str, str]]
    max_cost_usd: float
    max_cost_cap_usd: float
    cost_presets: list[float]
    catalog: dict[str, list[dict[str, str]]]
    schemes: list[dict[str, str]]
    fonts: list[dict[str, str]]
    aspects: list[dict[str, Any]]
    labels: dict[str, str]
