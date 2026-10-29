import base64
import binascii
import json
import logging
import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from sitegen.errors import CostLimit, LlmError
from sitegen.settings import settings

log = logging.getLogger(__name__)

#в тестах подменяется целиком
Llm = Callable[..., Any]


class Budget:
    #расходы одной операции
    def __init__(self, limit: float):
        self.limit = limit
        self.spent = 0.0
        # нет cost в ответе, значит не знаем
        self.known = True

    def add(self, cost: float | None) -> None:
        if cost is None:
            self.known = False
        else:
            self.spent += float(cost)

    def check(self) -> None:
        if self.spent >= self.limit:
            raise CostLimit(f"Достигнут лимит расходов на операцию: ${self.spent:.4f} из ${self.limit:.4f}")


# (цена за токен запроса, цена за токен ответа)
Price = tuple[float, float]
# url -> (когда скачали, модели)
_catalog: dict[str, tuple[float, list[dict[str, Any]]]] = {}
CATALOG_TTL = 3600
#грубая оценка, кириллица режется на токены мельче
CHARS_PER_TOKEN = 2.5
# если влезает меньше, ответ всё равно обрежется, нет смысла платить
MIN_ANSWER_TOKENS = 1500


def list_models(http: httpx.Client | None = None) -> list[dict[str, Any]]:
    # каталог отдаётся без ключа, кэшируем на час
    url = settings.openrouter_url
    cached = _catalog.get(url)
    if cached and time.monotonic() - cached[0] < CATALOG_TTL:
        return cached[1]
    own = http is None
    client = http or httpx.Client(timeout=15)
    try:
        resp = client.get(f"{url}/models")
    except httpx.HTTPError:
        return cached[1] if cached else []
    finally:
        if own:
            client.close()
    if resp.status_code != 200:
        return cached[1] if cached else []
    models = []
    try:
        for item in resp.json().get("data", []):
            p = item.get("pricing") or {}
            arch = item.get("architecture") or {}
            models.append({
                "id": str(item["id"]),
                "name": str(item.get("name") or item["id"]),
                "prompt": float(p.get("prompt", 0)),
                "completion": float(p.get("completion", 0)),
                #есть только у моделей картинок
                "image_output": float(p.get("image_output", 0)),
                "makes_images": "image" in (arch.get("output_modalities") or []),
            })  # fmt: skip
    except (ValueError, TypeError, AttributeError, KeyError):
        return cached[1] if cached else []
    _catalog[url] = (time.monotonic(), models)
    return models


def model_price(http: httpx.Client, model: str) -> Price | None:
    for item in list_models(http):
        if item["id"] == model:
            return item["prompt"], item["completion"]
    return None


def fit_max_tokens(messages: list[dict[str, str]], max_tokens: int, budget: Budget, price: Price | None) -> int:
    #max_tokens режем так, чтоб даже самый длинный ответ влез в лимит
    if price is None or price[1] <= 0:
        return max_tokens
    prompt_tokens = sum(len(m["content"]) for m in messages) / CHARS_PER_TOKEN
    left = budget.limit - budget.spent - prompt_tokens * price[0]
    allowed = int(left / price[1])
    if allowed < MIN_ANSWER_TOKENS:
        raise CostLimit(
            f"До лимита ${budget.limit:.4f} не хватит на ответ этой модели, потрачено ${budget.spent:.4f}. "
            "Поднимите MAX_COST_USD или выберите модель дешевле"
        )
    return min(max_tokens, allowed)


class _Transient(Exception):
    #сеть, 429, 5xx: можно повторить
    pass


def extract_json(text: str) -> dict[str, Any]:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("в ответе нет JSON-объекта")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"невалидный JSON: {e}") from None
    if not isinstance(data, dict):
        raise ValueError("ожидался JSON-объект")
    return data


def _request(
    http: httpx.Client,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    budget: Budget,
    price: Price | None = None,
) -> str:
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        #без этого стоимость в ответе не приходит
        "usage": {"include": True},
    }
    headers = {"Authorization": "Bearer " + settings.api_key()}
    try:
        resp = http.post(f"{settings.openrouter_url}/chat/completions", json=body, headers=headers)
    except httpx.HTTPError as e:
        # берём только тип ошибки, в тексте может быть лишнее
        raise _Transient(f"сетевая ошибка ({type(e).__name__})") from None

    if resp.status_code in (429, 500, 502, 503, 504):
        raise _Transient(f"OpenRouter ответил {resp.status_code}")
    if resp.status_code != 200:
        if resp.status_code in (401, 403):
            raise LlmError("OpenRouter не принял ключ, проверьте его на странице «Ключ» в панели")
        if resp.status_code == 402:
            raise LlmError("На балансе OpenRouter не хватает денег")
        try:
            msg = hide_key(str(resp.json()["error"]["message"]))[:300]
        except (ValueError, KeyError, TypeError):
            msg = ""
        raise LlmError(f"OpenRouter вернул {resp.status_code}: {msg}")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise _Transient("ответ OpenRouter в неожиданном формате") from None

    usage = data.get("usage") or {}
    cost = usage.get("cost")
    if cost is None and price is not None and "prompt_tokens" in usage:
        #cost не пришёл, считаем сами по тарифу
        cost = usage["prompt_tokens"] * price[0] + usage.get("completion_tokens", 0) * price[1]
    budget.add(cost)
    log.info("openrouter model=%s tokens=%s cost=%s", model, usage.get("total_tokens"), usage.get("cost"))
    if not content:
        raise _Transient("пустой ответ модели")
    return str(content)


def hide_key(text: str) -> str:
    # вдруг openrouter вернёт ключ прямо в тексте ошибки
    key = settings.api_key()
    return text.replace(key, "***") if key else text


def require_key() -> None:
    if not settings.has_key():
        raise LlmError(
            "Ключ OpenRouter не задан на сервере: введите его на странице «Ключ» в панели "
            "или впишите OPENROUTER_API_KEY в .env"
        )


def chat_json(
    model: str,
    messages: list[dict[str, str]],
    budget: Budget,
    validate: Callable[[dict[str, Any]], Any] | None = None,
    temperature: float = 0.9,
    max_tokens: int = 6000,
    client: httpx.Client | None = None,
) -> Any:
    require_key()

    http = client or httpx.Client(timeout=settings.request_timeout)
    messages = list(messages)
    attempts = settings.max_retries + 1
    last_error = ""
    try:
        price = model_price(http, model)
        if price is None:
            log.warning("тариф модели %s неизвестен, лимит расходов проверяется только по факту", model)
        for attempt in range(attempts):
            budget.check()
            tokens = fit_max_tokens(messages, max_tokens, budget, price)
            try:
                content = _request(http, model, messages, temperature, tokens, budget, price)
            except _Transient as e:
                last_error = str(e)
                log.warning("попытка %s из %s: %s", attempt + 1, attempts, last_error)
                time.sleep(min(2**attempt, 8))
                continue
            try:
                data = extract_json(content)
                return validate(data) if validate else data
            except ValueError as e:
                # сюда же падает ValidationError от pydantic
                last_error = str(e)[:1500]
                log.warning("попытка %s из %s: ответ не прошёл проверку", attempt + 1, attempts)
                #отдаём модели её ответ и ошибку, пусть исправит
                fix = f"Ответ не прошёл проверку: {last_error}\nВерни исправленный JSON целиком."
                messages += [{"role": "assistant", "content": content[:6000]}, {"role": "user", "content": fix}]
    finally:
        if client is None:
            http.close()

    budget.check()
    raise LlmError(f"Модель не дала корректный ответ за {attempts} попыток. Последняя ошибка: {last_error}")


# картинка приходит строкой data:image/...;base64
ImageMaker = Callable[..., bytes]
DATA_URL = re.compile(r"^data:image/(png|jpeg|jpg|webp);base64,(.+)$", re.S)
MAX_IMAGE_BYTES = 15 * 1024 * 1024


def _image_from(data: dict[str, Any]) -> bytes:
    message = data["choices"][0]["message"]
    for item in message.get("images") or []:
        url = (item.get("image_url") or {}).get("url", "")
        m = DATA_URL.match(url)
        if m:
            raw = base64.b64decode(m.group(2), validate=False)
            if 0 < len(raw) <= MAX_IMAGE_BYTES:
                return raw
    raise _Transient("модель не вернула картинку")


def generate_image(model: str, prompt: str, budget: Budget, client: httpx.Client | None = None) -> bytes:
    require_key()
    http = client or httpx.Client(timeout=settings.request_timeout)
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "modalities": ["image", "text"],
            "usage": {"include": True}}  # fmt: skip
    headers = {"Authorization": "Bearer " + settings.api_key()}
    attempts = settings.max_retries + 1
    last_error = ""
    try:
        for attempt in range(attempts):
            budget.check()
            try:
                try:
                    resp = http.post(f"{settings.openrouter_url}/chat/completions", json=body, headers=headers)
                except httpx.HTTPError as e:
                    raise _Transient(f"сетевая ошибка ({type(e).__name__})") from None
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise _Transient(f"OpenRouter ответил {resp.status_code}")
                if resp.status_code in (401, 403):
                    raise LlmError("OpenRouter не принял ключ, проверьте его на странице «Ключ» в панели")
                if resp.status_code == 402:
                    raise LlmError("На балансе OpenRouter не хватает денег")
                if resp.status_code != 200:
                    raise LlmError(f"OpenRouter вернул {resp.status_code}, модель {model} картинки, видимо, не рисует")
                try:
                    data = resp.json()
                except ValueError:
                    raise _Transient("ответ OpenRouter в неожиданном формате") from None
                budget.add((data.get("usage") or {}).get("cost"))
                try:
                    return _image_from(data)
                except (KeyError, IndexError, TypeError, ValueError, binascii.Error):
                    raise _Transient("ответ OpenRouter в неожиданном формате") from None
            except _Transient as e:
                last_error = str(e)
                log.warning("картинка, попытка %s из %s: %s", attempt + 1, attempts, last_error)
                time.sleep(min(2**attempt, 8))
    finally:
        if client is None:
            http.close()
    budget.check()
    raise LlmError(f"Модель не нарисовала картинку за {attempts} попыток. Последняя ошибка: {last_error}")
