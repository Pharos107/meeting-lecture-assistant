"""Số gộp 6 bài (bỏ hop1) của vòng 11-09 so với turbo + vá + greedy vòng 11-05 và PhoWhisper 11-03."""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as E
B = Path("E:/lehai/Documents/Project/STT/Báo Cáo")
old3 = json.load(open(B / "do-cer-2026-11-03/results.json", encoding="utf-8"))
old5 = json.load(open(B / "do-cer-2026-11-05/results.json", encoding="utf-8"))
new = json.load(open(HERE / "results.json", encoding="utf-8"))
SETS = {"turbo 11-05 vá+greedy": old5["large-v3-turbo-greedy"], "turbo 11-09": new["large-v3-turbo-1109"], "turbo 11-09b": new["large-v3-turbo-1109b"], "turbo 11-09c": new["large-v3-turbo-1109c"], "turbo 11-09d": new["large-v3-turbo-1109d"],
        "phowhisper 11-03": old3["phowhisper-large"]}
C6 = ["quahat", "phoi21", "phoi42", "aldehyd", "acid", "hop2"]
ref_len = {c: len(" ".join(t for _, t in E.read_reference(E.DATA / E.CLIPS[c]["ref"]))) for c in E.CLIPS}
for name, R in SETS.items():
    N = sum(R[c]["ref_words"] for c in C6); S_ = sum(R[c]["sub"] for c in C6); D = sum(R[c]["del"] for c in C6); I = sum(R[c]["ins"] for c in C6)
    cer = sum(R[c]["cer"] * ref_len[c] for c in C6) / sum(ref_len[c] for c in C6)
    el = sum(R[c]["run"]["elapsed"] for c in E.CLIPS); du = sum(R[c]["run"]["duration_ms"] for c in E.CLIPS) / 1000
    fl = sum(len(R[c]["flagged_segments"]) for c in E.CLIPS)
    print(f"{name:22} WER {(S_ + D + I) / N:.2%} CER {cer:.2%} S{S_} D{D} I{I} flagged(7) {fl} RTF(7) {el / du:.3f}")
print()
for c in E.CLIPS:
    print(c, " | ".join(f"{n}: CER {R[c]['cer']:.2%} D{R[c]['del']} I{R[c]['ins']} gap {R[c]['max_gaps'][0] if R[c]['max_gaps'] else None}" for n, R in SETS.items()))
print("\n== Đoạn mất chữ liền nhau (>=12 từ), vòng 11-09")
for c in E.CLIPS:
    runs = new["large-v3-turbo-1109d"][c]["del_runs"]
    print(f"  {c}: {len(runs)} đoạn, {sum(x['n'] for x in runs)} từ")
    for x in runs:
        print(f"     t={x['t']}s n={x['n']} {x['text'][:80]}")
print("\nflagged:", [(c, f) for c in E.CLIPS for f in new["large-v3-turbo-1109d"][c]["flagged_segments"]])
