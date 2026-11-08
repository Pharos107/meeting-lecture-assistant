"""Kẹp mẫu PCM hỏng và thêm khoảng VAD bỏ trống mà to."""

import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET", "t" * 32)

import numpy as np

from app.services.audio_processor import slice_pcm
from app.services.stt_engine import SAMPLE_RATE, add_loud_gaps


def tone(seconds: float, amplitude: float) -> np.ndarray:
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


class AudioRobustnessTests(unittest.TestCase):
    def test_broken_samples_are_clamped(self) -> None:
        # hop1 giây 1423: khung Opus hỏng giải mã ra mẫu 26933.
        pcm = tone(1.0, 0.5)
        pcm[100] = 26933.0
        pcm[200] = -500.0
        piece = slice_pcm(pcm, 0.0, 1.0)
        self.assertLessEqual(float(np.abs(piece).max()), 1.0)
        self.assertEqual(piece.dtype, np.float32)

    def test_vad_input_is_clamped_without_touching_the_file(self) -> None:
        import tempfile
        from pathlib import Path

        from app.services.stt_engine import _clamped_view

        folder = Path(tempfile.mkdtemp())
        path = folder / "a.f32"
        data = tone(25.0, 0.5)
        data[20 * SAMPLE_RATE] = 26933.0
        data.tofile(path)
        pcm = np.memmap(path, dtype="<f4", mode="r")
        fixed = _clamped_view(pcm)
        self.assertLessEqual(float(np.abs(fixed).max()), 1.0)
        self.assertEqual(float(fixed[100]), float(data[100]))
        # File gốc không đổi, memmap đọc lại vẫn còn mẫu hỏng.
        self.assertEqual(float(np.memmap(path, dtype="<f4", mode="r")[20 * SAMPLE_RATE]), 26933.0)
        clean = tone(1.0, 0.5)
        self.assertIs(_clamped_view(clean), clean)
        del pcm, fixed

    def test_loud_gap_is_added_and_quiet_gap_is_not(self) -> None:
        # 0-5 lời nói, 5-10 to như lời nói mà VAD bỏ, 10-15 lời nói, 15-20 gần lặng, 20-25 lời nói.
        pcm = np.concatenate([tone(5, 0.3), tone(5, 0.3), tone(5, 0.3), tone(5, 0.005), tone(5, 0.3)])
        regions = [(0.0, 5.0), (10.0, 15.0), (20.0, 25.0)]
        self.assertEqual(add_loud_gaps(pcm, regions), [(0.0, 5.0), (5.0, 10.0), (10.0, 15.0), (20.0, 25.0)])

    def test_short_gaps_and_silence_are_left_alone(self) -> None:
        pcm = np.concatenate([tone(5, 0.3), tone(2, 0.3), tone(5, 0.3)])
        self.assertEqual(add_loud_gaps(pcm, [(0.0, 5.0), (7.0, 12.0)]), [(0.0, 5.0), (7.0, 12.0)])
        self.assertEqual(add_loud_gaps(tone(10, 0.3), []), [])


class LoopFilterTests(unittest.TestCase):
    def test_looping_segment_is_dropped(self) -> None:
        from types import SimpleNamespace

        from app.services.stt_engine import WhisperEngine

        def word(text, start, end):
            return SimpleNamespace(word=f" {text}", start=start, end=end)

        real = SimpleNamespace(text=" Chất này có tên là gì?", start=0.0, end=2.0, compression_ratio=1.3,
                               words=[word("Chất", 0.0, 0.5), word("này", 0.5, 1.0), word("có", 1.0, 2.0)])
        loop = SimpleNamespace(text=" Nói bạn, ví dụ như đây, thể chất" + " CH3," * 30, start=2.0, end=25.0,
                               compression_ratio=6.2, words=[word("CH3,", 2.0, 3.0)])

        class Model:
            def transcribe(self, audio, **options):
                return iter([real, loop]), None

        produced = WhisperEngine(model=Model()).transcribe(np.zeros(16000, dtype=np.float32), None)
        self.assertEqual([item["text"] for item in produced], ["Chất này có tên là gì?"])

    def test_real_long_sentence_is_not_a_loop(self) -> None:
        from app.services.stt_engine import compression_ratio, is_hallucination

        # Câu thật có tỉ lệ nén cao nhất của vòng 11-09, hop1 giây 374.
        text = ("Ừ cái thứ nhất là chúng ta học về việc gì đã cần làm rõ luôn cũng đừng có phức tạp quá đây "
                "nhưng mà cũng đừng làm được rõ ràng thì chúng ta mới có thể làm được việc")
        self.assertLess(compression_ratio(text), 2.4)
        self.assertFalse(is_hallucination(text))
        self.assertTrue(is_hallucination("hay là vết tinh," + " và vết tinh," * 25))
