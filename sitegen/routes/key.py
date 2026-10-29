from fastapi import APIRouter

from sitegen.api_models import KeyIn, KeyOut
from sitegen.core import apikey
from sitegen.settings import settings

router = APIRouter(prefix="/api/key", tags=["key"])


# сам ключ ни один ответ не возвращает, только признаки
@router.get("", response_model=KeyOut)
def get_key(check: bool = False) -> KeyOut:
    out = apikey.status()
    if check and out["has_key"]:
        out |= apikey.check_key(settings.api_key())
    return KeyOut(**out)


@router.put("", response_model=KeyOut)
def put_key(body: KeyIn) -> KeyOut:
    return KeyOut(**apikey.save(body.key.get_secret_value()))


@router.delete("", response_model=KeyOut)
def delete_key() -> KeyOut:
    return KeyOut(**apikey.delete())
