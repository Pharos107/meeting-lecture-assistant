"""Tiến trình Celery. Hàng gpu chạy nhận dạng và hồ sơ giọng. Hàng io chạy LLM."""

import os

from celery import Celery

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("meeting", broker=redis_url)
celery_app.conf.task_routes = {
    "app.tasks.transcribe_upload": {"queue": "gpu"},
    "app.tasks.run_live_session": {"queue": "gpu"},
    "app.tasks.enroll_voice": {"queue": "gpu"},
    "app.tasks.run_llm": {"queue": "io"},
}
celery_app.conf.worker_prefetch_multiplier = 1


@celery_app.task(name="app.tasks.transcribe_upload", bind=True, max_retries=None)
def transcribe_upload(self, job_id: str):
    from app.services.pipeline import run_upload_job

    if run_upload_job(job_id) == "retry":
        raise self.retry(countdown=5)


@celery_app.task(name="app.tasks.run_live_session")
def run_live_session(session_id: str) -> None:
    """Worker giữ gpu:lock của phiên, đọc PCM, rồi gọi pipeline bản chuẩn."""
    return None


@celery_app.task(name="app.tasks.enroll_voice", bind=True, max_retries=None)
def enroll_voice(self, profile_id: str):
    from app.services.gpu_lock import get_gpu_lock

    from app.services.gpu_lock import keeper

    if not get_gpu_lock().acquire(str(profile_id)):
        raise self.retry(countdown=5)
    keeper.start(str(profile_id))
    try:
        return None
    finally:
        keeper.stop(str(profile_id))
        get_gpu_lock().release(str(profile_id))


@celery_app.task(name="app.tasks.run_llm")
def run_llm(run_id: str) -> None:
    from app.services.llm_runner import execute_llm_run

    execute_llm_run(run_id)
