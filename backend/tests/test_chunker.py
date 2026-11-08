"""Cắt vùng nói và khử từ nằm bên kia biên chồng."""

import unittest

from app.services.vad_chunker import TimedWord, build_chunks, drop_overlapping_words, empty_spans, fill_empty_spans


def words(*spans: tuple[float, float]) -> dict:
    return {
        "start": spans[0][0],
        "end": spans[-1][1],
        "text": " ".join("x" for _ in spans),
        "words": [{"text": "x", "start": start, "end": end} for start, end in spans],
    }


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


class EmptySpanTests(unittest.TestCase):
    def test_long_gaps_inside_a_region_are_found(self) -> None:
        # Chunk 100–120 s, mốc từ tương đối trong chunk.
        chunk = build_chunks([(100, 120)])[0]
        produced = [words((0.0, 1.0), (1.2, 2.0)), words((6.0, 7.0), (7.5, 8.0))]
        self.assertEqual(empty_spans(chunk, produced), [(102.0, 106.0), (108.0, 120.0)])

    def test_short_gaps_and_the_silence_between_regions_are_ignored(self) -> None:
        chunk = build_chunks([(0, 5), (6, 10)])[0]
        produced = [words((0.0, 4.0)), words((5.0, 5.2)), words((6.2, 9.5))]
        self.assertEqual(empty_spans(chunk, produced), [])

    def test_a_whole_empty_chunk_is_not_retried_on_the_same_audio(self) -> None:
        chunk = build_chunks([(0, 25)])[0]
        self.assertEqual(empty_spans(chunk, []), [])

    def test_each_empty_region_of_a_chunk_is_retried_alone(self) -> None:
        chunk = build_chunks([(0, 8), (9, 20)])[0]
        self.assertEqual(empty_spans(chunk, []), [(0, 8), (9, 20)])

    def test_retry_is_shifted_into_the_chunk_and_sorted(self) -> None:
        chunk = build_chunks([(100, 120)])[0]
        calls: list[tuple[float, float]] = []

        def transcribe(piece):
            calls.append((piece.start, piece.end))
            return [words((0.5, 1.0), (1.0, 2.0))]

        produced = [words((0.0, 1.0)), words((15.0, 20.0))]
        merged = fill_empty_spans(chunk, produced, transcribe)
        self.assertEqual(calls, [(101.0, 115.0)])
        self.assertEqual([raw["words"][0]["start"] for raw in merged], [0.0, 1.5, 15.0])
        self.assertEqual((merged[1]["start"], merged[1]["end"]), (1.5, 3.0))
        self.assertEqual(produced[0]["words"][0]["start"], 0.0)

    def test_greedy_retry_runs_only_when_the_span_stays_empty(self) -> None:
        chunk = build_chunks([(0, 8), (9, 20)])[0]
        retried: list[tuple[float, float]] = []

        def transcribe(piece):
            return [words((0.0, 1.0))] if piece.start == 0 else []

        def retry(piece):
            retried.append((piece.start, piece.end))
            return [words((0.5, 1.5))]

        merged = fill_empty_spans(chunk, [], transcribe, retry)
        self.assertEqual(retried, [(9, 20)])
        self.assertEqual([raw["words"][0]["start"] for raw in merged], [0.0, 9.5])

    def test_whole_empty_chunk_goes_straight_to_greedy(self) -> None:
        # #19, đầu bài phoi42: beam ra lời mời đăng ký kênh phủ cả chunk, bộ lọc xóa, chunk trống.
        chunk = build_chunks([(0.2, 22.2)])[0]
        beam_calls: list[tuple[float, float]] = []
        retried: list[tuple[float, float]] = []

        def transcribe(piece):
            beam_calls.append((piece.start, piece.end))
            return []

        def retry(piece):
            retried.append((piece.start, piece.end))
            return [words((0.5, 1.5)), words((3.0, 4.0))]

        merged = fill_empty_spans(chunk, [], transcribe, retry)
        self.assertEqual(beam_calls, [])
        self.assertEqual(retried, [(0.2, 22.2)])
        self.assertEqual([raw["words"][0]["start"] for raw in merged], [0.5, 3.0])

    def test_no_retry_keeps_the_old_behaviour(self) -> None:
        chunk = build_chunks([(0, 8), (9, 20)])[0]
        self.assertEqual(fill_empty_spans(chunk, [], lambda piece: []), [])
