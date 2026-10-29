from collections.abc import Iterator
from typing import Any

import httpx
import keyring
import pytest
from fastapi.testclient import TestClient
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError, PasswordDeleteError
from pydantic import SecretStr

from sitegen.core import apikey
from sitegen.settings import settings

GOOD = "sk-or-v1-" + "a1b2c3d4" * 8
OTHER = "sk-or-v1-" + "ffee0011" * 8


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.data.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.data[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.data:
            raise PasswordDeleteError("нет")
        del self.data[(service, username)]


@pytest.fixture
def vault(monkeypatch: pytest.MonkeyPatch) -> Iterator[MemoryKeyring]:
    #в .env пусто, хранилище в памяти
    old = keyring.get_keyring()
    mem = MemoryKeyring()
    keyring.set_keyring(mem)
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "use_keyring", True)
    monkeypatch.setattr(apikey, "check_key", lambda key, client=None: {"checked": True, "limit": 5.0, "usage": 0.25})
    yield mem
    keyring.set_keyring(old)


def test_save_change_and_delete(client: TestClient, vault: MemoryKeyring):
    r = client.get("/api/key").json()
    assert r["has_key"] is False
    assert r["editable"] is True

    r = client.put("/api/key", json={"key": GOOD})
    assert r.status_code == 200
    body = r.json()
    assert body["has_key"] is True
    assert body["hint"] == "sk-or-...c3d4"
    assert body["limit"] == 5.0
    assert GOOD not in r.text
    assert settings.api_key() == GOOD
    assert client.get("/api/config").json()["key_source"] == "из хранилища учётных данных"

    # замена
    client.put("/api/key", json={"key": OTHER})
    assert settings.api_key() == OTHER

    r = client.delete("/api/key")
    assert r.status_code == 200
    assert r.json()["has_key"] is False
    assert settings.has_key() is False
    assert client.delete("/api/key").status_code == 404


def test_saved_key_is_used_for_generation(client: TestClient, vault: MemoryKeyring):
    assert client.post("/api/companies/generate", json={"aspects": []}).status_code == 502
    client.put("/api/key", json={"key": GOOD})
    assert client.post("/api/companies/generate", json={"aspects": []}).json()["status"] == "done"


def test_get_never_returns_key(client: TestClient, vault: MemoryKeyring):
    client.put("/api/key", json={"key": GOOD})
    for url in ("/api/key", "/api/key?check=true", "/api/config"):
        assert GOOD not in client.get(url).text


@pytest.mark.parametrize("bad", ["", "sk-or-", "sk-or-v1 с пробелом 1234567", "sk-proj-abcdefghijklmnop", "x" * 300])
def test_bad_format_is_rejected(client: TestClient, vault: MemoryKeyring, bad: str):
    r = client.put("/api/key", json={"key": bad})
    assert r.status_code in (400, 422)
    assert vault.data == {}
    #ключ в ошибке не повторяем, а sk-or- там есть в подсказке
    if len(bad) > 10:
        assert bad not in r.text


def test_key_rejected_by_openrouter_is_not_saved(client: TestClient, vault: MemoryKeyring, monkeypatch):
    def refuse(key: str, client: Any = None) -> dict[str, Any]:
        from sitegen.errors import AppError

        raise AppError("OpenRouter не принял этот ключ")

    monkeypatch.setattr(apikey, "check_key", refuse)
    r = client.put("/api/key", json={"key": GOOD})
    assert r.status_code == 400
    assert vault.data == {}


def test_env_key_blocks_editing(client: TestClient):
    # в тестах ключ задан переменной окружения
    body = client.get("/api/key").json()
    assert body["editable"] is False
    assert ".env" in body["note"]
    assert client.put("/api/key", json={"key": GOOD}).status_code == 400
    assert client.delete("/api/key").status_code == 400


def test_disabled_keyring_blocks_editing(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "use_keyring", False)
    assert "USE_KEYRING" in client.get("/api/key").json()["note"]


def test_broken_store_gives_clear_error(client: TestClient, vault: MemoryKeyring, monkeypatch):
    def boom(*a: Any) -> None:
        raise KeyringError("нет хранилища")

    monkeypatch.setattr(keyring, "set_password", boom)
    r = client.put("/api/key", json={"key": GOOD})
    assert r.status_code == 400
    assert "недоступно" in r.json()["detail"]


def test_foreign_site_cannot_change_key(client: TestClient, vault: MemoryKeyring):
    r = client.put("/api/key", json={"key": GOOD}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert vault.data == {}


# ---------- проверка ключа у OpenRouter ----------

def checker(code: int, body: Any = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/key")
        return httpx.Response(code, json=body if body is not None else {})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_check_key_reads_limit_and_usage():
    info = apikey.check_key(GOOD, checker(200, {"data": {"limit": 10, "usage": 1.5}}))
    assert info == {"checked": True, "limit": 10, "usage": 1.5}


def test_check_key_rejects_bad_key():
    from sitegen.errors import AppError

    with pytest.raises(AppError, match="не принял"):
        apikey.check_key(GOOD, checker(401))


def test_check_key_unknown_answer_is_not_fatal():
    assert apikey.check_key(GOOD, checker(500)) == {"checked": False}
    assert apikey.check_key(GOOD, checker(200, ["не словарь"])) == {"checked": False}

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет сети")

    assert apikey.check_key(GOOD, httpx.Client(transport=httpx.MockTransport(down))) == {"checked": False}
