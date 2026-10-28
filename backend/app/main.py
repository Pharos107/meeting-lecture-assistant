"""Ứng dụng FastAPI."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes_auth import router as auth_router
from app.api.routes_events import router as events_router
from app.api.routes_export import router as export_router
from app.api.routes_jobs import media_router
from app.api.routes_jobs import router as jobs_router
from app.api.routes_live import router as live_router
from app.api.routes_llm import router as llm_router
from app.api.routes_voice import router as voice_router
from app.core.exceptions import ApiError

app = FastAPI(title="Trợ lý biên bản họp và bài giảng")
app.include_router(auth_router)
app.include_router(jobs_router)
app.include_router(media_router)
app.include_router(events_router)
app.include_router(export_router)
app.include_router(live_router)
app.include_router(llm_router)
app.include_router(voice_router)


@app.exception_handler(ApiError)
def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.body())


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
