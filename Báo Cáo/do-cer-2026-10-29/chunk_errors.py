"""Lỗi theo vị trí so với mép chunk, và nguyên nhân các đoạn bị mất (VAD hay Whisper).

Dùng: python -I -X utf8 chunk_errors.py [runs_dir] [chunks.json]
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate  # noqa: E402
import score  # noqa: E402

runs = HERE / (sys.argv[1] if len(sys.argv) > 1 else "runs")
chunks_all = json.load(open(HERE / (sys.argv[2] if len(sys.argv) > 2 else "chunks.json"), encoding="utf-8"))
STEMS = {"phapluat": "phapluat", "coso2": "coso2", "thegioi": "thegioi"}


def timed_tokens(tr):
    out = []
    for seg in tr["segments"]:
        if evaluate.is_flagged(seg):
            continue
        words = []
        for w in seg["words"]:
            if words and re.match(r"^[.,]\d{3}\b", w["text"]) and words[-1][0][-1:].isdigit():
                words[-1][0] += w["text"]
                words[-1][2] = w["end_ms"] / 1000
            else:
                words.append([w["text"], w["start_ms"] / 1000, w["end_ms"] / 1000])
        for text, a, b in words:
            out += [(t, (a + b) / 2) for t in score.norm_tokens(text)]
    return out


def analyse(model, clip, key):
    meta = evaluate.CLIPS[clip]
    ref = [t for _, t in score.read_reference(str(evaluate.DATA / meta["ref"]))]
    tr = json.load(open(runs / model / f"{clip}.json", encoding="utf-8"))
    hyp = timed_tokens(tr)
    hw = [t for t, _ in hyp]
    pairs = score.align(ref, hw)
    chunks = chunks_all[key]["chunks"]
    bounds = sorted({c[0] for c in chunks} | {c[1] for c in chunks})

    # Thời điểm cho từng từ của bản gỡ băng: lấy từ máy đã căn, từ bị mất thì nội suy.
    rt = [None] * len(ref)
    err = [False] * len(ref)
    for i, j in pairs:
        if i is not None:
            if j is not None:
                rt[i] = hyp[j][1]
                err[i] = ref[i] != hw[j]
            else:
                err[i] = True
    known = [k for k, t in enumerate(rt) if t is not None]
    for k in range(len(ref)):
        if rt[k] is None:
            prev = max((x for x in known if x < k), default=None)
            nxt = min((x for x in known if x > k), default=None)
            if prev is None:
                rt[k] = rt[nxt]
            elif nxt is None:
                rt[k] = rt[prev]
            else:
                rt[k] = rt[prev] + (rt[nxt] - rt[prev]) * (k - prev) / (nxt - prev)
    ins_t = [hyp[j][1] for i, j in pairs if i is None]

    def dist(t):
        return min(abs(t - b) for b in bounds)

    buckets = {"≤1 s": (0, 1), "1–3 s": (1, 3), ">3 s": (3, 1e9)}
    res = {}
    for name, (lo, hi) in buckets.items():
        idx = [k for k in range(len(ref)) if lo <= dist(rt[k]) < hi or (lo == 0 and dist(rt[k]) == 0)]
        e = sum(err[k] for k in idx) + sum(1 for t in ins_t if lo <= dist(t) < hi)
        res[name] = (len(idx), e / max(len(idx), 1))

    # Đoạn mất liền nhau từ 5 từ trở lên.
    runs_del = []
    k = 0
    dels = {i for i, j in pairs if j is None}
    while k < len(ref):
        if k in dels:
            s = k
            while k in dels:
                k += 1
            if k - s >= 5:
                a = rt[s - 1] if s > 0 else 0
                b = rt[k] if k < len(ref) else chunks_all[key]["duration"]
                mid = (a + b) / 2
                inside = any(c[0] <= mid <= c[1] for c in chunks)
                runs_del.append((round(a, 1), round(b, 1), k - s, "trong chunk" if inside else "ngoài VAD",
                                 " ".join(ref[s:min(k, s + 12)])))
        else:
            k += 1
    return res, runs_del


for model in ["large-v3-turbo", "phowhisper-large"]:
    for clip in ["phapluat", "coso2", "thegioi"]:
        res, dels = analyse(model, clip, clip)
        print(f"{model:16} {clip:8} " + "  ".join(f"{n}: {c} từ, lỗi {r:.1%}" for n, (c, r) in res.items()))
        for d in dels:
            print("      mất", d)
