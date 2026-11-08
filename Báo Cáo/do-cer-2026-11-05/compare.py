"""Số gộp của vòng 11-05 (turbo có fill_empty_spans, rồi thêm greedy) so với turbo và PhoWhisper vòng 11-03.

Dùng: python -I -X utf8 compare.py > raw-logs/compare.txt
Cùng cách gộp với do-cer-2026-11-03/analyze.py: 6 bài, bỏ hop1 vì bản gỡ băng bị lược.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as E  # noqa: E402

old = json.load(open(HERE.parent / "do-cer-2026-11-03" / "results.json", encoding="utf-8"))
new = json.load(open(HERE / "results.json", encoding="utf-8"))
SETS = {
    "turbo 11-03": old["large-v3-turbo"],
    "turbo 11-05 (fill)": new["large-v3-turbo"],
    "phowhisper 11-03": old["phowhisper-large"],
}
if "large-v3-turbo-greedy" in new:
    SETS["turbo 11-05 (fill+greedy)"] = new["large-v3-turbo-greedy"]
CLIPS6 = ["quahat", "phoi21", "phoi42", "aldehyd", "acid", "hop2"]
ref_len = {c: len(" ".join(t for _, t in E.read_reference(E.DATA / E.CLIPS[c]["ref"]))) for c in E.CLIPS}

print("== Gộp 6 bài (bỏ hop1)")
for name, R in SETS.items():
    N = sum(R[c]["ref_words"] for c in CLIPS6)
    S = sum(R[c]["sub"] for c in CLIPS6)
    D = sum(R[c]["del"] for c in CLIPS6)
    I = sum(R[c]["ins"] for c in CLIPS6)
    ch = sum(ref_len[c] for c in CLIPS6)
    cer = sum(R[c]["cer"] * ref_len[c] for c in CLIPS6) / ch
    te = sum(R[c]["terms"]["term_exact"] for c in CLIPS6)
    tt = sum(R[c]["terms"]["term_total"] for c in CLIPS6)
    el = sum(R[c]["run"]["elapsed"] for c in E.CLIPS)
    du = sum(R[c]["run"]["duration_ms"] for c in E.CLIPS) / 1000
    fl = sum(len(R[c]["flagged_segments"]) for c in E.CLIPS)
    print(f"{name:20} WER {(S + D + I) / N:.2%} CER {cer:.2%} S{S} D{D} I{I} terms {te}/{tt} "
          f"flagged(7) {fl} RTF(7) {el / du:.3f}")

print("\n== Từng bài: CER, số từ mất, khoảng trống dài nhất (giây, tại giây)")
for c in E.CLIPS:
    row = [c]
    for name, R in SETS.items():
        gap = R[c]["max_gaps"][0] if R[c]["max_gaps"] else None
        row.append(f"{name}: CER {R[c]['cer']:.2%} D{R[c]['del']} gap {gap}")
    print(" | ".join(row))

for run in [r for r in ("large-v3-turbo", "large-v3-turbo-greedy") if r in new]:
    print(f"\n== Đoạn mất chữ liền nhau (>=12 từ) của {run} vòng 11-05")
    for c in E.CLIPS:
        for x in new[run][c]["del_runs"]:
            print(f"  {c} t={x['t']}s n={x['n']} {x['text'][:90]}")
