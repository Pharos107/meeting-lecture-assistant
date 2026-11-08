"""In từng câu thô của faster-whisper trên một khoảng, kèm lý do WhisperEngine bỏ câu."""
import sys, tempfile
from pathlib import Path
from app.services.audio_processor import load_pcm, normalize, slice_pcm
from app.services.pipeline import _whisper_engine
from app.services.stt_engine import HALLUCINATION_SILENCE_S, is_hallucination, too_fast, prompt_or_none

audio, lo, hi = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
work = Path(tempfile.mkdtemp())
normalize(Path(audio), work / "a.opus", work / "a.pcm", 10800)
pcm = load_pcm(work / "a.pcm")
engine = _whisper_engine()
for beam in (5, 1):
    segs, _ = engine.model.transcribe(slice_pcm(pcm, lo, hi), language="vi", task="transcribe", beam_size=beam,
        word_timestamps=True, condition_on_previous_text=False, vad_filter=False, temperature=0.0,
        compression_ratio_threshold=2.4, log_prob_threshold=-1.0, no_speech_threshold=0.6,
        hallucination_silence_threshold=HALLUCINATION_SILENCE_S, initial_prompt=None)
    print(f"== beam {beam}")
    for s in segs:
        n = len(s.text.split())
        print(f"  [{lo+s.start:.2f}-{lo+s.end:.2f}] dur={s.end-s.start:.2f} words={n} wps={n/max(s.end-s.start,1e-3):.1f} "
              f"fast={too_fast(s.text, s.start, s.end)} hall={is_hallucination(s.text)} nsp={s.no_speech_prob:.2f} lp={s.avg_logprob:.2f} | {s.text.strip()[:90]}")
    print("  app:", [r["text"][:50] for r in engine.transcribe(slice_pcm(pcm, lo, hi), None, greedy=(beam == 1))])
