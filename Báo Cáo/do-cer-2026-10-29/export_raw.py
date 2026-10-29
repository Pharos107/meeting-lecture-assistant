"""Xuất transcript thô đầy đủ ra .txt và dựng các đoạn so sánh song song cho báo cáo.

Dùng: python -I -X utf8 export_raw.py <thư mục xuất transcript> <file markdown đoạn so sánh>
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate  # noqa: E402
import score  # noqa: E402

out_dir = Path(sys.argv[1])
out_md = Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)

RUNS = {
    "turbo-truoc-sua": HERE / "runs" / "large-v3-turbo",
    "turbo-sau-sua": HERE / "runs_fixed" / "large-v3-turbo",
    "phowhisper-large": HERE / "runs" / "phowhisper-large",
    "turbo-nhieu-truoc-sua": HERE / "runs_noise" / "large-v3-turbo",
}
LABEL = {
    "turbo-truoc-sua": "large-v3-turbo, trước khi sửa",
    "turbo-sau-sua": "large-v3-turbo, sau khi sửa",
    "phowhisper-large": "PhoWhisper-large, thô",
    "turbo-nhieu-truoc-sua": "large-v3-turbo, trước khi sửa",
}


def clock(s: float) -> str:
    return f"{int(s // 60):02d}:{s % 60:04.1f}"


def line(seg) -> str:
    mark = "  ⚠ CÂU BỊA" if evaluate.is_flagged(seg) else ""
    return (f"[{clock(seg['start_ms'] / 1000)} → {clock(seg['end_ms'] / 1000)}] "
            f"{seg['speaker_label'] or '—'} | {seg['text_raw']}{mark}")


# 1. Transcript đầy đủ.
written = []
for tag, folder in RUNS.items():
    for path in sorted(folder.glob("*.json")):
        if path.name.endswith(".meta.json"):
            continue
        tr = json.load(open(path, encoding="utf-8"))
        meta_path = path.with_name(path.stem + ".meta.json")
        meta = json.load(open(meta_path, encoding="utf-8")) if meta_path.exists() else {}
        target = out_dir / f"{path.stem}__{tag}.txt"
        with open(target, "w", encoding="utf-8") as f:
            f.write(f"# {path.stem} — {LABEL[tag]}\n")
            f.write(f"# job {meta.get('job_id')} | {meta.get('status')} | {meta.get('elapsed')} s | "
                    f"stages {meta.get('stages')} | {len(tr['segments'])} câu\n\n")
            for seg in tr["segments"]:
                f.write(line(seg) + "\n")
        written.append(target.name)


# 2. Đoạn so sánh song song.
def ref_timeline(clip, tr):
    """Gán thời điểm ước lượng cho từng từ của bản gỡ băng bằng cách căn với một transcript có mốc thời gian."""
    ref = score.read_reference(str(evaluate.DATA / evaluate.CLIPS[clip]["ref"]))
    rw = [t for _, t in ref]
    hyp = []
    for seg in tr["segments"]:
        if evaluate.is_flagged(seg):
            continue
        for w in seg["words"]:
            for t in score.norm_tokens(w["text"]):
                hyp.append((t, (w["start_ms"] + w["end_ms"]) / 2000))
    pairs = score.align(rw, [t for t, _ in hyp])
    times = [None] * len(rw)
    for i, j in pairs:
        if i is not None and j is not None:
            times[i] = hyp[j][1]
    known = [k for k, t in enumerate(times) if t is not None]
    for k in range(len(rw)):
        if times[k] is None:
            prev = max((x for x in known if x < k), default=None)
            nxt = min((x for x in known if x > k), default=None)
            if prev is None or nxt is None:
                times[k] = times[prev if prev is not None else nxt]
            else:
                times[k] = times[prev] + (times[nxt] - times[prev]) * (k - prev) / (nxt - prev)
    return ref, times


WINDOWS = [
    ("phapluat", 20, 52, "PhoWhisper bịa hai câu ở cuối chunk (22,8 s và 49,0 s)."),
    ("phapluat", 66, 90, "turbo bịa \"La La School\" giữa câu; \"phòng cháy chữa cháy\"; \"răn đe\"."),
    ("coso2", 55, 112, "turbo bịa \"Ghiền Mì Gõ\" rồi bỏ trống 23 s; lời người nhà bệnh nhân (≈100–109 s)."),
    ("coso2", 135, 166, "Lời nữ bệnh nhân (≈145–153 s); số \"150.000\"."),
    ("thegioi", 85, 120, "Tên riêng nước ngoài: Araghchi, Tehran, Hormuz; PhoWhisper bịa ở 113,7 s. Câu \"nguyễn thiện kiêu "
                         "và nguyễn thiện trang\" ở 87,8 s cũng là câu bịa của PhoWhisper, nhưng chỉ 6,4 từ/giây nên quy tắc "
                         "lọc **không** bắt được. Như vậy bản \"đã lọc\" của PhoWhisper vẫn còn sót một ít chữ bịa."),
    ("thegioi", 748, 772, "\"drone\" và \"kinh tế tầm thấp\"."),
]

md = []
for clip, a, b, note in WINDOWS:
    runs = {tag: json.load(open(RUNS[tag] / f"{clip}.json", encoding="utf-8"))
            for tag in ["turbo-truoc-sua", "turbo-sau-sua", "phowhisper-large"]}
    ref, times = ref_timeline(clip, runs["turbo-sau-sua"])
    md.append(f"#### `{clip}` {clock(a)}–{clock(b)}\n\n{note}\n")
    md.append("**Bản gỡ băng** (đã chuẩn hóa: chữ thường, bỏ dấu câu, số đọc thành chữ; thời điểm ước lượng bằng căn từ):\n")
    speaker, words, blocks = None, [], []
    for (spk, tok), t in zip(ref, times):
        if a <= t <= b:
            if spk != speaker and words:
                blocks.append(f"{speaker}: {' '.join(words)}")
                words = []
            speaker = spk
            words.append(tok)
    if words:
        blocks.append(f"{speaker}: {' '.join(words)}")
    md.append("```text\n" + "\n".join(blocks) + "\n```\n")
    for tag, tr in runs.items():
        segs = [s for s in tr["segments"] if s["end_ms"] / 1000 > a and s["start_ms"] / 1000 < b]
        md.append(f"**{LABEL[tag]}:**\n")
        md.append("```text\n" + ("\n".join(line(s) for s in segs) or "(không có chữ)") + "\n```\n")

# Một đoạn bản nhiễu.
for name, a, b in [("babble_10db", 34, 60), ("babble_5db", 202, 234)]:
    md.append(f"#### `{name}` {clock(a)}–{clock(b)} (bài phapluat trộn tiếng người nói)\n")
    for tag in ["turbo-nhieu-truoc-sua", "turbo-sau-sua"]:
        tr = json.load(open(RUNS[tag] / f"{name}.json", encoding="utf-8"))
        segs = [s for s in tr["segments"] if s["end_ms"] / 1000 > a and s["start_ms"] / 1000 < b]
        md.append(f"**{LABEL[tag]}:**\n")
        md.append("```text\n" + ("\n".join(line(s) for s in segs) or "(không có chữ)") + "\n```\n")

out_md.write_text("\n".join(md), encoding="utf-8")
print("transcripts:", len(written), "->", out_dir)
print("excerpts ->", out_md)
