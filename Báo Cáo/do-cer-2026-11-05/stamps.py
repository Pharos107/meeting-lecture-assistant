"""In câu trả lời của từng câu hỏi, kèm đoạn transcript ở mỗi mốc [MM:SS] được trích, để chấm bằng tay.

Dùng: python -I -X utf8 stamps.py qa_out.json > raw-logs/qa_stamps.txt

Với mỗi mốc, in câu có start_ms trùng mốc (theo giây) nếu có, không thì câu chứa mốc đó.
"exact" là mốc trùng đầu một câu của transcript gửi cho LLM, "inside" là mốc nằm trong một câu, "none" là ngoài mọi câu.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAMP = re.compile(r"\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]")

out = json.load(open(sys.argv[1], encoding="utf-8"))
transcripts = {clip: json.load(open(HERE / "runs" / "large-v3-turbo" / f"{clip}.json", encoding="utf-8"))
               for clip in {a["clip"] for a in out["answers"]}}


def text_of(seg):
    return seg.get("text_edited") or seg["text_raw"]


def locate(segments, second):
    for seg in segments:
        if seg["start_ms"] // 1000 == second:
            return "exact", seg
    for seg in segments:
        if seg["start_ms"] <= second * 1000 < seg["end_ms"]:
            return "inside", seg
    return "none", None


for a in out["answers"]:
    segs = transcripts[a["clip"]]["segments"]
    print("=" * 100)
    print(f"{a['id']} [{a['kind']}] {a['question']}")
    print(f"  status={a['status']} ttft={a['ttft_s']}s total={a['total_s']}s usage={a.get('usage')}")
    print("  expected:", " | ".join(a["expected"]))
    print("-- answer:")
    print(a["answer"])
    print("-- stamps:")
    for m in STAMP.finditer(a["answer"]):
        if m.group(3):
            second = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        else:
            second = int(m.group(1)) * 60 + int(m.group(2))
        kind, seg = locate(segs, second)
        shown = f"{seg['start_ms'] / 1000:.1f}s {seg.get('speaker_name') or seg.get('speaker_label')}: {text_of(seg)[:220]}" if seg else ""
        print(f"  {m.group(0)} {kind}: {shown}")
