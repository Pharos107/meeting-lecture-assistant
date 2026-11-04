"""Ghi danh hồ sơ giọng. Kiến trúc mục 2.5, luồng F9.

Vector của hồ sơ phải so được với vector cụm mà `diarization.cluster_vectors` tính trong buổi họp.
Vì vậy mẫu đi qua đúng `diarization.diarize` với một người nói, rồi lấy vector của nhãn đó.
"""

import logging
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import get_engine
from app.models import VoiceProfile

logger = logging.getLogger(__name__)

MIN_SPEECH_MS = 15_000
# API đã chặn mẫu ngoài 20 đến 40 giây bằng ffprobe. Trần ở đây chỉ để FFmpeg không chạy mãi.
MAX_SAMPLE_SECONDS = 60


class EnrollError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _real_regions(pcm):
    from app.services.stt_engine import speech_regions

    return speech_regions(pcm)


def _real_diarize(pcm, num_speakers):
    from app.services.diarization import diarize

    return diarize(pcm, num_speakers)


def speech_ms(regions: list[tuple[float, float]]) -> int:
    return int(round(sum(max(0.0, end - start) for start, end in regions) * 1000))


def pick_vector(vectors: dict[str, list[float]]) -> list[float] | None:
    """Mẫu có một người nói, nên chỉ có một nhãn. Còn nhiều hơn thì lấy nhãn đầu theo tên."""
    for label in sorted(vectors):
        vector = vectors[label]
        if vector:
            return vector
    return None


def run_enroll(profile_id: str, *, diarize_fn=None, regions_fn=None) -> str:
    """Điểm vào của worker. Trả retry khi chưa giữ được gpu:lock."""
    from app.services.gpu_lock import get_gpu_lock, keeper

    owner = str(profile_id)
    lock = get_gpu_lock()
    if not lock.acquire(owner):
        with Session(get_engine()) as db:
            row = _load(db, profile_id)
            if row is None or row.status != "processing":
                return "done"
        return "retry"
    keeper.start(owner)
    try:
        with Session(get_engine()) as db:
            row = _load(db, profile_id)
            if row is None or row.status != "processing":
                return "done"
            enroll(db, row, diarize_fn=diarize_fn or _real_diarize, regions_fn=regions_fn or _real_regions)
        return "done"
    finally:
        keeper.stop(owner)
        lock.release(owner)


def _load(db: Session, profile_id: str) -> VoiceProfile | None:
    try:
        return db.get(VoiceProfile, uuid.UUID(str(profile_id)))
    except ValueError:
        return None


def enroll(db: Session, row: VoiceProfile, *, diarize_fn, regions_fn) -> None:
    """Chuẩn hóa mẫu sang Opus, đo tiếng bằng VAD, tính vector, rồi ghi `ready` hoặc `failed`."""
    from app.services.audio_processor import MediaError, close_pcm, load_pcm, normalize
    from app.services.diarization import PIPELINE_MODEL
    from app.services.speaker_align import pack_embedding

    root = Path(get_settings().data_dir).resolve()
    profile_id = row.id
    pcm_path = root / "tmp" / f"voice-{profile_id}.f32"
    pcm = None
    opus_path: Path | None = None
    try:
        if not row.sample_path or not Path(row.sample_path).is_file():
            raise EnrollError("Không còn file mẫu giọng.")
        source = Path(row.sample_path)
        opus_path = source.with_name(f"{profile_id}.opus")
        audio = normalize(source, opus_path, pcm_path, MAX_SAMPLE_SECONDS)
        if source.resolve() != opus_path.resolve():
            source.unlink(missing_ok=True)

        pcm = load_pcm(pcm_path)
        spoken = speech_ms(regions_fn(pcm))
        if spoken < MIN_SPEECH_MS:
            seconds = f"{spoken / 1000:.1f}".replace(".", ",")
            raise EnrollError(f"Mẫu chỉ còn {seconds} giây có tiếng, cần ít nhất 15 giây.")
        _turns, vectors, _device = diarize_fn(pcm, 1)
        vector = pick_vector(vectors)
        if vector is None:
            raise EnrollError("Không tính được vector giọng từ mẫu này.")

        if not _still_there(db, row):
            opus_path.unlink(missing_ok=True)
            return
        row.sample_path = str(opus_path)
        row.duration_ms = audio.duration_ms
        row.embedding = pack_embedding(vector)
        row.embedding_dim = len(vector)
        row.embedding_model = PIPELINE_MODEL
        row.error_message = None
        row.status = "ready"
        db.commit()
    except EnrollError as error:
        _fail(db, row, error.message, opus_path)
    except MediaError as error:
        _fail(db, row, error.message, opus_path)
    except Exception:
        logger.exception("Hồ sơ giọng %s lỗi khi ghi danh.", profile_id)
        _fail(db, row, "Worker gặp lỗi khi tính vector giọng.", opus_path)
    finally:
        close_pcm(pcm)
        pcm_path.unlink(missing_ok=True)


def _still_there(db: Session, row: VoiceProfile) -> bool:
    """Người dùng có thể xóa hồ sơ trong lúc worker đang tính."""
    db.expire(row)
    try:
        db.refresh(row)
    except Exception:
        db.rollback()
        return False
    return True


def _fail(db: Session, row: VoiceProfile, message: str, opus_path: Path | None) -> None:
    db.rollback()
    if not _still_there(db, row):
        if opus_path is not None:
            opus_path.unlink(missing_ok=True)
        return
    if opus_path is not None and opus_path.is_file():
        row.sample_path = str(opus_path)
    row.status = "failed"
    row.error_message = message
    db.commit()
