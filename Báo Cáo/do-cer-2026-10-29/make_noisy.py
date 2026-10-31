"""Trộn nhiễu hồng và nhiễu tiếng người (babble) vào một bài sạch ở các mức SNR.

SNR tính theo công suất trung bình của vùng có tiếng (Silero VAD) so với công suất nhiễu.
Dùng (trong worker-gpu): python make_noisy.py clean.mp3 outdir babble1.mp3 babble2.mp3
"""
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

from app.services.audio_processor import SAMPLE_RATE, load_pcm, normalize
from app.services.stt_engine import speech_regions

SNRS = [20, 10, 5, 0]


def pcm_of(path):
    tmp = Path(tempfile.mkdtemp())
    normalize(Path(path), tmp / "a.opus", tmp / "a.f32", 10800)
    return np.array(load_pcm(tmp / "a.f32"), dtype=np.float64)


def write_wav(path, x):
    peak = np.max(np.abs(x))
    if peak > 0.99:
        x = x * (0.99 / peak)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((x * 32767).astype("<i2").tobytes())


clean = pcm_of(sys.argv[1])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
n = len(clean)
mask = np.zeros(n, dtype=bool)
for a, b in speech_regions(clean.astype(np.float32)):
    mask[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)] = True
p_speech = np.mean(clean[mask] ** 2)

rng = np.random.default_rng(7)
white = rng.standard_normal(n)
spec = np.fft.rfft(white)
freqs = np.fft.rfftfreq(n, 1 / SAMPLE_RATE)
spec[1:] /= np.sqrt(freqs[1:])
spec[0] = 0
pink = np.fft.irfft(spec, n)

sources = [pcm_of(p) for p in sys.argv[3:]]
babble = np.zeros(n)
for k in range(4):
    src = sources[k % len(sources)]
    off = int((60 + 137 * k) * SAMPLE_RATE) % max(len(src) - n, 1)
    babble += src[off:off + n] if len(src) - off >= n else np.resize(src[off:], n)

for name, noise in [("pink", pink), ("babble", babble)]:
    p_noise = np.mean(noise ** 2)
    for snr in SNRS:
        gain = np.sqrt(p_speech / (p_noise * 10 ** (snr / 10)))
        write_wav(out / f"{name}_{snr}db.wav", clean + gain * noise)
        print(name, snr, "dB written", flush=True)
