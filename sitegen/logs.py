import json
import logging
import uuid
from contextvars import ContextVar

# запросы идут параллельно, поэтому contextvar
request_id: ContextVar[str] = ContextVar("request_id", default="-")


class _AddRequestId(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False)


def setup(as_json: bool = False) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_AddRequestId())
    if as_json:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # httpx пишет в info полный url запроса, нам не надо
    logging.getLogger("httpx").setLevel(logging.WARNING)


def new_request_id(incoming: str | None) -> str:
    #чужой id не берём как есть
    if incoming and len(incoming) <= 64 and incoming.replace("-", "").isalnum():
        return incoming
    return uuid.uuid4().hex[:12]
