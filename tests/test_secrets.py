import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from scripts import check_secrets
from sitegen import settings as settings_module
from sitegen.settings import settings

ROOT = Path(__file__).resolve().parent.parent
FAKE = "sk-or-v1-" + "0123456789abcdef" * 4


def test_scanner_finds_key_and_masks_it():
    found = check_secrets.scan_text("a.env", f"x=1\nOPENROUTER_API_KEY={FAKE}\n")
    assert len(found) == 1
    assert found[0].startswith("a.env:2:")
    # сам ключ в выводе не печатаем
    assert FAKE not in found[0]


def test_scanner_ignores_placeholders():
    assert check_secrets.scan_text("x", "OPENROUTER_API_KEY=\nkey sk-or-test-key\n") == []


def test_repository_has_no_keys():
    assert check_secrets.scan(staged=False) == []


def test_env_example_has_empty_key():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "OPENROUTER_API_KEY=" in lines


def test_env_file_is_forbidden(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(check_secrets, "_git", lambda *a: ".env\nREADME.md\n" if a[0] == "ls-files" else "")
    found = check_secrets.scan(staged=False)
    assert any(".env: этот файл нельзя" in f for f in found)


def test_new_files_are_scanned_too(monkeypatch: pytest.MonkeyPatch):
    calls = []

    def git(*args: str) -> str:
        calls.append(args)
        return ""

    monkeypatch.setattr(check_secrets, "_git", git)
    check_secrets.scan(staged=False)
    #без --others новые файлы не видно
    assert ("ls-files", "--cached", "--others", "--exclude-standard") in calls


def test_works_without_git(tmp_path, monkeypatch: pytest.MonkeyPatch):
    def no_git(*args: str) -> str:
        raise subprocess.CalledProcessError(128, "git")

    (tmp_path / "app.py").write_text(f"KEY = '{FAKE}'\n", encoding="utf-8")
    (tmp_path / "sub dir").mkdir()
    (tmp_path / "sub dir" / "notes.md").write_text("ключа тут нет\n", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text(f"x = '{FAKE}'\n", encoding="utf-8")
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(check_secrets, "_git", no_git)
    monkeypatch.chdir(tmp_path)

    names, in_git = check_secrets.project_files()
    assert in_git is False
    assert "sub dir/notes.md" in names and ".venv/lib.py" not in names
    found = check_secrets.scan(staged=False)
    assert len(found) == 1 and found[0].startswith("app.py:1")


def test_key_from_file(tmp_path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "key"
    path.write_text("  sk-or-from-file \n", encoding="utf-8")
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "openrouter_api_key_file", str(path))
    assert settings.api_key() == "sk-or-from-file"
    assert settings.key_source() == "из файла-секрета"


def test_missing_key_file_is_not_fatal(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "openrouter_api_key_file", str(tmp_path / "нет"))
    assert settings.has_key() is False


def test_key_from_keyring(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "use_keyring", True)
    monkeypatch.setattr(settings_module, "_from_keyring", lambda: "sk-or-from-vault")
    assert settings.api_key() == "sk-or-from-vault"
    assert settings.key_source() == "из хранилища учётных данных"


def test_env_key_wins_over_others(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "use_keyring", True)
    monkeypatch.setattr(settings_module, "_from_keyring", lambda: "sk-or-from-vault")
    assert settings.api_key() == "sk-or-test-key"


def test_broken_keyring_is_not_fatal(monkeypatch: pytest.MonkeyPatch):
    import keyring

    def boom(*a):
        raise RuntimeError("нет хранилища")

    monkeypatch.setattr(keyring, "get_password", boom)
    assert settings_module._from_keyring() == ""


def test_config_says_where_key_is_from(client: TestClient):
    body = client.get("/api/config").json()
    assert body["key_source"] == "из переменной окружения или .env"
    assert "sk-or-test-key" not in client.get("/api/config").text


def test_staged_binary_files_are_skipped(monkeypatch: pytest.MonkeyPatch):
    # фото примеров в коммите: раньше хук на них падал
    monkeypatch.setattr(check_secrets, "_git", lambda *a: "photo.jpg\nREADME.md\n")
    files = {"photo.jpg": b"\xff\xd8\xff\xe0 jpeg", "README.md": f"key {FAKE}".encode()}

    def staged(name: str) -> str:
        return files[name].decode("utf-8")

    monkeypatch.setattr(check_secrets, "_staged", staged)
    found = check_secrets.scan(staged=True)
    assert len(found) == 1 and found[0].startswith("README.md:1")
