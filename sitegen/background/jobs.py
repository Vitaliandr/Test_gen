import logging
import threading
import uuid
from collections.abc import Callable

from sitegen.clients.openrouter import Budget
from sitegen.errors import AppError
from sitegen.settings import settings

log = logging.getLogger(__name__)

MAX_JOBS = 200

#в тестах включаем, чтоб не ждать поток
run_inline = False


class Job:
    def __init__(self, limit: float | None = None) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.status = "running"
        self.stage = "В очереди"
        self.error: str | None = None
        #готово, но не всё, например один раздел упал
        self.warning: str | None = None
        self.result_id: int | None = None
        self.budget = Budget(settings.max_cost_usd if limit is None else limit)

    def set_stage(self, text: str) -> None:
        self.stage = text


Work = Callable[[Job], int]

_jobs: dict[str, Job] = {}


def _run(job: Job, work: Work) -> None:
    try:
        job.result_id = work(job)
        job.status = "done"
        job.stage = "Готово"
    except AppError as e:
        job.status, job.error = "error", e.message
    except Exception:
        #трейс в лог, пользователю не показываем
        log.exception("задача %s упала", job.id)
        job.status, job.error = "error", "внутренняя ошибка, подробности в логе сервера"


def start(work: Work, limit: float | None = None) -> Job:
    job = Job(limit)
    _jobs[job.id] = job
    # старые чистим, а running ещё опрашивают
    finished = [k for k, j in _jobs.items() if j.status != "running"]
    for old in finished[: max(len(_jobs) - MAX_JOBS, 0)]:
        del _jobs[old]
    if run_inline:
        _run(job, work)
    else:
        threading.Thread(target=_run, args=(job, work), daemon=True).start()
    return job


def busy() -> bool:
    return any(j.status == "running" for j in _jobs.values())


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)
