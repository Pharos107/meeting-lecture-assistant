"""pyannote speaker-diarization-3.1. Kiến trúc mục 2.5."""

import os

import numpy as np

from app.services.audio_processor import SAMPLE_RATE
from app.services.speaker_align import SpeakerTurn
from app.services.stt_engine import _is_oom, free_cuda

PIPELINE_MODEL = "pyannote/speaker-diarization-3.1"
VECTOR_SECONDS = 30.0
MIN_VECTOR_SECONDS = 1.0


def _load_pipeline():
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(PIPELINE_MODEL, use_auth_token=os.environ.get("HF_TOKEN") or None)
    if pipeline is None:
        raise RuntimeError("Không tải được pipeline pyannote. Kiểm tra HF_TOKEN và điều kiện của repo.")
    return pipeline


def cluster_vectors(pipeline, annotation, waveform) -> dict[str, list[float]]:
    """Một vector cho mỗi nhãn, lấy từ tối đa 30 giây tiếng không chồng người khác."""
    import torch

    overlap = annotation.get_overlap()
    vectors: dict[str, list[float]] = {}
    for label in annotation.labels():
        timeline = annotation.label_timeline(label).support()
        if overlap:
            timeline = timeline.extrude(overlap)
        pieces = []
        total = 0.0
        for segment in timeline:
            take = min(segment.duration, VECTOR_SECONDS - total)
            if take <= 0:
                break
            start = int(segment.start * SAMPLE_RATE)
            pieces.append(waveform[0, start : start + int(take * SAMPLE_RATE)])
            total += take
        if total < MIN_VECTOR_SECONDS:
            continue
        clip = torch.cat(pieces)[None, None, :]
        embedding = np.asarray(pipeline._embedding(clip))
        if embedding.size == 0 or np.isnan(embedding).any():
            continue
        vectors[str(label)] = embedding[0].astype(float).tolist()
    return vectors


def _run(pipeline, audio: dict, num_speakers: int | None, device: str):
    import torch

    pipeline.to(torch.device(device))
    options = {"num_speakers": num_speakers} if num_speakers else {}
    annotation = pipeline(audio, **options)
    turns = [
        SpeakerTurn(int(round(segment.start * 1000)), int(round(segment.end * 1000)), str(label))
        for segment, _track, label in annotation.itertracks(yield_label=True)
    ]
    return turns, cluster_vectors(pipeline, annotation, audio["waveform"])


def diarize(pcm: np.ndarray, num_speakers: int | None) -> tuple[list[SpeakerTurn], dict[str, list[float]], str]:
    """Chạy trên cuda, hết VRAM thì chạy lại trên cpu. Luôn giải phóng pipeline."""
    import torch

    waveform = torch.from_numpy(np.array(pcm, dtype=np.float32)).unsqueeze(0)
    audio = {"waveform": waveform, "sample_rate": SAMPLE_RATE}
    pipeline = _load_pipeline()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    try:
        try:
            turns, vectors = _run(pipeline, audio, num_speakers, device)
        except RuntimeError as error:
            if device != "cuda" or not _is_oom(error):
                raise
            pipeline.to(torch.device("cpu"))
            free_cuda()
            device = "cpu"
            turns, vectors = _run(pipeline, audio, num_speakers, device)
        return turns, vectors, device
    finally:
        del pipeline
        free_cuda()
