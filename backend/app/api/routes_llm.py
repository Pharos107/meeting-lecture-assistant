"""Chuẩn hóa văn bản và lập biên bản."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes_auth import current_user, read_object, validation
from app.api.routes_jobs import ensure_mutable, highest_pass, invalid_state, not_found, owned_job
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.db import get_db
from app.models import LlmRun
from app.schemas.http import LlmBody, request_body
from app.services.dispatch import enqueue

router = APIRouter(prefix="/api", tags=["llm"], dependencies=[Depends(current_user)])


def run_json(run: LlmRun) -> dict:
    body = {
        "run_id": str(run.id),
        "task": run.task,
        "status": run.status,
        "model": run.model_name,
        "result": None if run.task == "clean" and run.status == "done" else run.result,
    }
    if run.task == "summarize" and run.template:
        body["template"] = run.template
    if run.status == "failed":
        body["error_code"] = run.error_code
        body["error_message"] = run.error_message
    if run.task == "clean" and run.status == "running" and isinstance(run.result, dict):
        body["result"] = None
    return body


@router.post("/jobs/{job_id}/llm", status_code=202, openapi_extra=request_body(LlmBody))
async def start_llm(job_id: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    ensure_mutable(job, highest_pass(db, job))
    if not get_settings().llm_model:
        raise ApiError(422, "llm_not_configured", "Chưa cấu hình model LLM.")
    data = await read_object(request)
    task = data.get("task")
    fields: dict[str, str] = {}
    if task not in {"clean", "summarize"}:
        fields["task"] = "Tác vụ phải là clean hoặc summarize."
    template = data.get("template")
    if task == "summarize" and template not in {"meeting", "lecture"}:
        fields["template"] = "Mẫu phải là meeting hoặc lecture."
    restart = data.get("restart", False)
    if not isinstance(restart, bool):
        fields["restart"] = "restart phải là đúng hoặc sai."
    validation(fields)
    running = db.scalar(select(LlmRun.id).where(LlmRun.job_id == job.id, LlmRun.status == "running"))
    if running is not None:
        raise invalid_state()
    run = LlmRun(
        job_id=job.id,
        task=task,
        template=template if task == "summarize" else None,
        status="running",
        model_name=get_settings().llm_model,
        result={"restart": True} if task == "clean" and restart else None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    enqueue("app.tasks.run_llm", str(run.id))
    return {"run_id": str(run.id), "task": run.task, "status": run.status}


@router.get("/jobs/{job_id}/llm/{task}")
def latest_llm(job_id: str, task: str, request: Request, db: Session = Depends(get_db)) -> dict:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    if task not in {"clean", "summarize"}:
        raise not_found()
    run = db.scalar(
        select(LlmRun)
        .where(LlmRun.job_id == job.id, LlmRun.task == task)
        .order_by(LlmRun.created_at.desc())
    )
    if run is None:
        raise not_found()
    return run_json(run)
