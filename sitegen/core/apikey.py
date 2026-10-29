import re
from typing import Any

import httpx
import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from sitegen.errors import AppError, NotFound
from sitegen.settings import KEY_SOURCES, KEYRING_SERVICE, KEYRING_USER, settings

KEY_RE = re.compile(r"^sk-or-[A-Za-z0-9_\-]{10,200}$")
NO_STORE = (
    "Хранилище учётных данных недоступно на этом сервере. "
    "Положите ключ в .env (OPENROUTER_API_KEY) или в файл (OPENROUTER_API_KEY_FILE)"
)


def hint(key: str) -> str:
    #хвоста хватит, чтоб отличить один ключ от другого
    return f"{key[:6]}...{key[-4:]}"


def _blocked() -> str:
    _, source = settings.key_with_source()
    if source == "env":
        return (
            "Ключ задан в .env или переменной окружения. "
            "Уберите его оттуда и перезапустите сервер, тогда ключом можно управлять здесь"
        )
    if source == "file":
        return "Ключ задан файлом OPENROUTER_API_KEY_FILE, управлять им из панели нельзя"
    if not settings.use_keyring:
        return "Хранилище отключено настройкой USE_KEYRING=false"
    return ""


def status() -> dict[str, Any]:
    key, source = settings.key_with_source()
    note = _blocked()
    return {
        "has_key": bool(key),
        "source": KEY_SOURCES.get(source, ""),
        "hint": hint(key) if key else "",
        "editable": not note,
        "note": note,
    }


def check_key(key: str, client: httpx.Client | None = None) -> dict[str, Any]:
    # заодно узнаём, сколько лимита осталось
    http = client or httpx.Client(timeout=15)
    try:
        resp = http.get(f"{settings.openrouter_url}/key", headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError:
        return {"checked": False}
    finally:
        if client is None:
            http.close()
    if resp.status_code in (401, 403):
        raise AppError("OpenRouter не принял этот ключ, проверьте, что он скопирован целиком")
    if resp.status_code != 200:
        return {"checked": False}
    try:
        data = resp.json().get("data") or {}
    except (ValueError, AttributeError):
        return {"checked": False}
    return {"checked": True, "limit": data.get("limit"), "usage": data.get("usage")}


def save(key: str) -> dict[str, Any]:
    key = key.strip()
    if not KEY_RE.match(key):
        raise AppError("Не похоже на ключ OpenRouter: он начинается с sk-or- и не содержит пробелов")
    note = _blocked()
    if note:
        raise AppError(note)
    #битый ключ не сохраняем, а если openrouter лежит, сохраняем как есть
    checked = check_key(key)
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
    except KeyringError:
        raise AppError(NO_STORE) from None
    return status() | checked


def delete() -> dict[str, Any]:
    note = _blocked()
    if note:
        raise AppError(note)
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except PasswordDeleteError:
        raise NotFound("В хранилище ключа нет") from None
    except KeyringError:
        raise AppError(NO_STORE) from None
    return status()
