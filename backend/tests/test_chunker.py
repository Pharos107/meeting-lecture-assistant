"""Cắt vùng nói và khử từ nằm bên kia biên chồng."""

import unittest

from app.services.vad_chunker import TimedWord, build_chunks, drop_overlapping_words


class ChunkerTests(unittest.TestCase):
    def test_long_region_overlaps_by_one_second(self) -> None:
        chunks = build_chunks([(0, 90)])
        self.assertEqual([(chunk.start, chunk.end) for chunk in chunks], [(0, 30), (29, 59), (58, 88), (87, 90)])
        self.assertTrue(all(chunk.end - chunk.start <= 30 for chunk in chunks))

    def test_gap_over_two_seconds_stays_split(self) -> None:
        chunks = build_chunks([(0, 10), (20, 30)])
        self.assertEqual(len(chunks), 2)

    def test_short_gap_merges_inside_thirty_seconds(self) -> None:
        chunks = build_chunks([(0, 10), (10.5, 20)])
        self.assertEqual(len(chunks), 1)
        self.assertEqual((chunks[0].start, chunks[0].end), (0, 20))

    def test_word_on_the_wrong_side_of_the_boundary_is_dropped(self) -> None:
        chunks = build_chunks([(0, 60)])
        words = [
            TimedWord("giữ-trước", 29.2, 29.4, 0),
            TimedWord("bỏ-trước", 29.4, 29.8, 0),
            TimedWord("bỏ-sau", 29.2, 29.4, 1),
            TimedWord("giữ-sau", 29.4, 29.8, 1),
            TimedWord("đuôi", 58.2, 59.0, 2),
        ]
        kept = [word.text for word in drop_overlapping_words(words, chunks)]
        self.assertEqual(kept, ["giữ-trước", "giữ-sau", "đuôi"])
