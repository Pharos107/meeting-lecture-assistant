"""Gán nhãn từ và khớp hồ sơ giọng."""

import unittest

from app.services.speaker_align import (
    SpeakerTurn,
    VoiceProfileVector,
    label_for_word,
    match_speakers,
)


class SpeakerTests(unittest.TestCase):
    def test_half_overlap_counts_and_less_does_not(self) -> None:
        turns = [SpeakerTurn(0, 500, "SPEAKER_00")]
        self.assertEqual(label_for_word(0, 1000, turns), "SPEAKER_00")
        self.assertIsNone(label_for_word(0, 1001, turns))

    def test_margin_drops_a_contested_cluster(self) -> None:
        profiles = [
            VoiceProfileVector("a", [1.0, 0.0], "pyannote/speaker-diarization-3.1"),
            VoiceProfileVector("b", [0.99, 0.1410673598], "pyannote/speaker-diarization-3.1"),
            VoiceProfileVector("old", [1.0, 0.0], "pipeline-cũ"),
        ]
        mapping = match_speakers(
            {"SPEAKER_00": [1.0, 0.0]},
            profiles,
            current_model="pyannote/speaker-diarization-3.1",
        )
        self.assertEqual(mapping, {})

    def test_clear_score_keeps_one_profile(self) -> None:
        profiles = [
            VoiceProfileVector("lan", [1.0, 0.0], "pyannote/speaker-diarization-3.1"),
            VoiceProfileVector("binh", [0.0, 1.0], "pyannote/speaker-diarization-3.1"),
        ]
        mapping = match_speakers(
            {"SPEAKER_00": [1.0, 0.0], "SPEAKER_01": [0.0, 1.0]},
            profiles,
            current_model="pyannote/speaker-diarization-3.1",
        )
        self.assertEqual(mapping, {"SPEAKER_00": "lan", "SPEAKER_01": "binh"})
