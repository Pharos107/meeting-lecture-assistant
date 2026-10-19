"""Xuất transcript và biên bản."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.routes_auth import current_user, read_object, validation
from app.api.routes_jobs import ensure_mutable, highest_pass, owned_job
from app.db import get_db
from app.schemas.http import ExportBody, request_body
from app.services.exporter import content_disposition, export_job

router = APIRouter(prefix="/api", tags=["export"], dependencies=[Depends(current_user)])

_FORMATS = {"md", "docx", "pdf", "srt", "vtt"}
_TEXT = {"auto", "raw", "cleaned", "edited"}


@router.post("/jobs/{job_id}/exports", openapi_extra=request_body(ExportBody))
async def export(job_id: str, request: Request, db: Session = Depends(get_db)) -> Response:
    user = current_user(request, db)
    job = owned_job(db, user, job_id)
    ensure_mutable(job, highest_pass(db, job))
    data = await read_object(request)
    fields: dict[str, str] = {}
    fmt = data.get("format")
    mode = data.get("text", "auto")
    include = data.get("include_speakers", True)
    if fmt not in _FORMATS:
        fields["format"] = "Định dạng xuất không được hỗ trợ."
    if mode not in _TEXT:
        fields["text"] = "Lớp chữ không được hỗ trợ."
    if not isinstance(include, bool):
        fields["include_speakers"] = "include_speakers phải là đúng hoặc sai."
    validation(fields)
    body, media_type, extension = export_job(db, job, fmt, mode, include)
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": content_disposition(job.title, extension)},
    )
