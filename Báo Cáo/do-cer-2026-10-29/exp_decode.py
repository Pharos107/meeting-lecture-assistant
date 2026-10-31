"""Thử các cách sửa: hallucination_silence_threshold, chunk ngắn hơn, lọc nhiễu FFmpeg.

Chạy lại đúng chuỗi VAD → chunk → turbo → khử chồng như pipeline, không có diarization.
Dùng (trong worker-gpu): python exp_decode.py outdir name=file [name=file ...]
"""
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from faster_whisper import WhisperModel

from app.services import vad_chunker
from app.services.audio_processor import load_pcm, normalize, slice_pcm
from app.services.stt_engine import is_hallucination, speech_regions

BASE = dict(language="vi", task="transcribe", beam_size=5, word_timestamps=True, condition_on_previous_text=False,
            vad_filter=False, temperature=0.0, compression_ratio_threshold=2.4, log_prob_threshold=-1.0,
            no_speech_threshold=0.6)
CONFIGS = {
    "A_hien_tai": dict(max_chunk=30, extra={}, denoise=False),
    "B_halluc_silence": dict(max_chunk=30, extra={"hallucination_silence_threshold": 2.0}, denoise=False),
    "C_chunk15": dict(max_chunk=15, extra={}, denoise=False),
    "D_chunk15_halluc": dict(max_chunk=15, extra={"hallucination_silence_threshold": 2.0}, denoise=False),
    "E_afftdn": dict(max_chunk=30, extra={}, denoise=True),
}

import os  # noqa: E402

if os.environ.get("CFGS"):
    CONFIGS = {k: v for k, v in CONFIGS.items() if k in os.environ["CFGS"].split(",")}
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
model = WhisperModel("large-v3-turbo", device="cuda", compute_type="int8")
for item in sys.argv[2:]:
    name, src = item.split("=", 1)
    tmp = Path(tempfile.mkdtemp())
    normalize(Path(src), tmp / "a.opus", tmp / "a.f32", 10800)
    pcm_plain = load_pcm(tmp / "a.f32")
    den = tmp / "den.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-af", "afftdn=nf=-25:tn=1",
                    "-ac", "1", "-ar", "16000", str(den)], check=True)
    normalize(den, tmp / "d.opus", tmp / "d.f32", 10800)
    pcm_den = load_pcm(tmp / "d.f32")
    for cfg_name, cfg in CONFIGS.items():
        pcm = pcm_den if cfg["denoise"] else pcm_plain
        vad_chunker.MAX_CHUNK_S = cfg["max_chunk"]
        chunks = vad_chunker.build_chunks(speech_regions(pcm))
        t0 = time.time()
        segments = []
        for ci, chunk in enumerate(chunks):
            segs, _ = model.transcribe(slice_pcm(pcm, chunk.start, chunk.end), **{**BASE, **cfg["extra"]})
            for s in segs:
                if is_hallucination(s.text):
                    continue
                words = []
                for w in s.words or []:
                    tw = vad_chunker.TimedWord(w.word.strip(), chunk.start + w.start, chunk.start + w.end, ci)
                    if tw.text and vad_chunker.keep_word(tw, chunks):
                        words.append({"text": tw.text, "start_ms": int(tw.start * 1000), "end_ms": int(tw.end * 1000),
                                      "speaker_label": None})
                if words:
                    segments.append({"start_ms": words[0]["start_ms"], "end_ms": words[-1]["end_ms"],
                                     "text_raw": " ".join(w["text"] for w in words), "speaker_label": None,
                                     "words": words})
        dt = time.time() - t0
        json.dump({"segments": segments, "elapsed": dt, "chunks": len(chunks)},
                  open(out / f"{name}__{cfg_name}.json", "w", encoding="utf-8"), ensure_ascii=False)
        print(name, cfg_name, "chunks", len(chunks), "segments", len(segments), f"{dt:.1f}s", flush=True)
vad_chunker.MAX_CHUNK_S = 30
