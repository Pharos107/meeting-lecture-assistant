"""So chữ thô của pipeline trước và sau khi sửa stt_engine."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate  # noqa: E402
import score  # noqa: E402

chunks = json.load(open(HERE / "chunks.json", encoding="utf-8"))
ITEMS = [("phapluat", "phapluat", HERE / "runs" / "large-v3-turbo" / "phapluat.json"),
         ("coso2", "coso2", HERE / "runs" / "large-v3-turbo" / "coso2.json"),
         ("thegioi", "thegioi", HERE / "runs" / "large-v3-turbo" / "thegioi.json")]
for n in ["babble_10db", "babble_5db", "pink_5db", "pink_0db"]:
    ITEMS.append((n, "phapluat", HERE / "runs_noise" / "large-v3-turbo" / f"{n}.json"))


def speech_without_text(tr, regions):
    spans = sorted((w["start_ms"] / 1000 - 0.5, w["end_ms"] / 1000 + 0.5) for s in tr["segments"] for w in s["words"])
    total = 0.0
    for a, b in regions:
        cur = a
        for x, y in spans:
            if y < cur or x > b:
                continue
            if x - cur >= 1.5:
                total += min(x, b) - cur
            cur = max(cur, y)
            if cur >= b:
                break
        if b - cur >= 1.5:
            total += b - cur
    return total


def has_spaced_number(tr):
    import re
    return sum(bool(re.search(r"\d [.,%-]", s["text_raw"])) for s in tr["segments"])


out = {}
print(f"{'bài':12} {'WER trước':>10} {'WER sau':>8} {'CER trước':>10} {'CER sau':>8} {'bịa trước':>9} {'bịa sau':>7} "
      f"{'không chữ trước':>15} {'sau':>6} {'số bị tách':>10} {'thời gian':>14}")
for name, clip, before_path in ITEMS:
    meta = evaluate.CLIPS[clip]
    ref = score.read_reference(str(evaluate.DATA / meta["ref"]))
    regions = [(a, b) for a, b, _ in chunks[clip]["regions"]]
    row = {}
    for tag, path in [("before", before_path), ("after", HERE / "runs_fixed" / "large-v3-turbo" / f"{name}.json")]:
        tr = json.load(open(path, encoding="utf-8"))
        _, m = evaluate.text_metrics(ref, evaluate.hyp_tokens(tr, drop_flagged=False), meta["terms"])
        mp = path.with_name(path.stem + ".meta.json")
        row[tag] = {"wer": m["wer"], "cer": m["cer"], "sdi": (m["sub"], m["del"], m["ins"]),
                    "term_cer": m["terms"]["term_cer"], "flagged": sum(evaluate.is_flagged(s) for s in tr["segments"]),
                    "swt": speech_without_text(tr, regions), "spaced": has_spaced_number(tr),
                    "elapsed": json.load(open(mp, encoding="utf-8"))["elapsed"] if mp.exists() else None}
    out[name] = row
    b, a = row["before"], row["after"]
    print(f"{name:12} {b['wer']:10.2%} {a['wer']:8.2%} {b['cer']:10.2%} {a['cer']:8.2%} {b['flagged']:9} {a['flagged']:7} "
          f"{b['swt']:14.1f}s {a['swt']:5.1f}s {b['spaced']:4} → {a['spaced']:<3} {b['elapsed']}→{a['elapsed']}s")
json.dump(out, open(HERE / "results_fix.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
