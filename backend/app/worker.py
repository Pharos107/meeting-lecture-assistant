"""Tiến trình Celery. Hàng gpu chạy nhận dạng và hồ sơ giọng. Hàng io chạy LLM."""

import logging
import os

from celery import Celery
from celery.signals import celeryd_after_setup

log = logging.getLogger(__name__)

GPU_TIME_LIMIT_S = 6 * 3600
LLM_TIME_LIMIT_S = 30 * 60

redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("meeting", broker=redis_url)
celery_app.conf.task_routes = {
    "app.tasks.transcribe_upload": {"queue": "gpu"},
    "app.tasks.run_live_session": {"queue": "gpu"},
    "app.tasks.enroll_voice": {"queue": "gpu"},
    "app.tasks.run_llm": {"queue": "io"},
}
celery_app.conf.worker_prefetch_multiplier = 1
celery_app.conf.task_acks_late = True
celery_app.conf.task_reject_on_worker_lost = True
# Dài hơn hạn cứng 6 giờ của task GPU, để task chưa ack không bị giao lần hai.
celery_app.conf.broker_transport_options = {"visibility_timeout": 25200}


@celeryd_after_setup.connect
def check_gpu(sender, instance, **_kwargs) -> None:
    """Worker hàng gpu ghi tên card và VRAM. Thiếu CUDA thì thoát ngay."""
    queues = set(instance.app.amqp.queues.consume_from or {})
    if "gpu" not in queues:
        return
    if os.environ.get("WHISPER_DEVICE", "cuda") != "cuda":
        log.warning("WHISPER_DEVICE khác cuda. Worker gpu chạy trên CPU, chỉ dùng để thử.")
        return
    import torch

    if not torch.cuda.is_available():
        raise SystemExit("Worker gpu cần CUDA. Kiểm tra driver NVIDIA, Container Toolkit, và wheel PyTorch CUDA.")
    props = torch.cuda.get_device_properties(0)
    log.info("GPU %s, VRAM %.1f GB", props.name, props.total_memory / 1024**3)


@celery_app.task(name="app.tasks.transcribe_upload", bind=True, max_retries=None, time_limit=GPU_TIME_LIMIT_S)
def transcribe_upload(self, job_id: str):
    from app.services.pipeline import run_upload_job

    if run_upload_job(job_id) == "retry":
        raise self.retry(countdown=5)


@celery_app.task(name="app.tasks.run_live_session", time_limit=GPU_TIME_LIMIT_S)
def run_live_session(session_id: str) -> None:
    """Worker giữ gpu:lock của phiên, đọc PCM, rồi gọi pipeline bản chuẩn."""
    return None


@celery_app.task(name="app.tasks.enroll_voice", bind=True, max_retries=None, time_limit=GPU_TIME_LIMIT_S)
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


@celery_app.task(name="app.tasks.run_llm", time_limit=LLM_TIME_LIMIT_S)
def run_llm(run_id: str) -> None:
    from app.services.llm_runner import execute_llm_run

    execute_llm_run(run_id)
