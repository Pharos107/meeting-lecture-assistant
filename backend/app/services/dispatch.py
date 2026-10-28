"""Đưa tác vụ vào Celery khi có REDIS_URL."""

import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def enqueue(task_name: str, argument: str) -> None:
    if not get_settings().redis_url:
        return
    try:
        from app.worker import celery_app

        celery_app.send_task(task_name, args=[argument])
    except Exception:
        logger.warning("Không đưa được tác vụ %s vào hàng.", task_name)
