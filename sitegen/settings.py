import logging
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

# под этими именами ключ лежит в диспетчере учётных данных
KEYRING_SERVICE = "sitegen-openrouter"
KEYRING_USER = "api-key"

KEY_SOURCES = {
    "env": "из переменной окружения или .env",
    "file": "из файла-секрета",
    "keyring": "из хранилища учётных данных",
}


def _from_keyring() -> str:
    try:
        import keyring

        return (keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or "").strip()
    except Exception:
        #на сервере хранилища нет, NoKeyringError, падать не надо
        return ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///data/app.db"
    sites_dir: str = "data/sites"
    # сгенерированные фото команды
    media_dir: str = "data/media"

    #SecretStr, чтоб ключ не светился в repr
    openrouter_api_key: SecretStr = SecretStr("")
    #файл, где лежит только ключ, для docker secrets
    openrouter_api_key_file: str = ""
    use_keyring: bool = True
    openrouter_url: str = "https://openrouter.ai/api/v1"
    # доп модели в панель, через запятую
    openrouter_models: str = ""
    default_model: str = "openai/gpt-4o-mini"
    default_image_model: str = "google/gemini-3.1-flash-lite-image"
    max_cost_usd: float = 0.10
    #чтоб опечатка 50 вместо 0.50 не съела баланс
    max_cost_cap_usd: float = 5.0
    max_retries: int = 2
    request_timeout: float = 120

    docs: bool = True
    log_json: bool = False
    allowed_hosts: str = "localhost,127.0.0.1"

    def models(self) -> list[str]:
        return [m.strip() for m in self.openrouter_models.split(",") if m.strip()]

    def key_with_source(self) -> tuple[str, str]:
        # сначала env, потом файл, потом хранилище
        key = self.openrouter_api_key.get_secret_value().strip()
        if key:
            return key, "env"
        if self.openrouter_api_key_file:
            try:
                key = Path(self.openrouter_api_key_file).read_text(encoding="utf-8").strip()
            except OSError:
                log.warning("файл с ключом %s не читается", self.openrouter_api_key_file)
                key = ""
            if key:
                return key, "file"
        if self.use_keyring:
            key = _from_keyring()
            if key:
                return key, "keyring"
        return "", ""

    def api_key(self) -> str:
        return self.key_with_source()[0]

    def key_source(self) -> str:
        return KEY_SOURCES.get(self.key_with_source()[1], "")

    def has_key(self) -> bool:
        return bool(self.api_key())


settings = Settings()
