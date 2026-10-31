"""Chấm mọi cặp (bài, model) trong runs/ và ghi results.json cho báo cáo.

Dùng: python -I -X utf8 evaluate.py
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import score  # noqa: E402

DATA = Path("E:/lehai/Documents/Project/STT/data/phóng sự 7p")
FILLERS = {"thì", "ấy", "ạ", "vâng", "dạ", "à", "ừ", "ờ", "ơ", "ừm", "cái"}
MAX_WORDS_PER_SECOND = 12
HALLUCINATION_MARKERS = ("subscribe", "la la school", "đăng ký kênh", "đăng kí kênh", "theo dõi kênh",
                         "cảm ơn các bạn đã theo dõi", "cảm ơn các bạn đã xem", "bỏ lỡ những video")

CLIPS = {
    "phapluat": {
        "title": "Nâng cao ý thức, trách nhiệm của nhân dân trước pháp luật",
        "audio": "Nâng cao ý thức, trách nhiệm của nhân dân trước pháp luật  VTV24 - VTV24.mp3",
        "ref": "Phụ đề _Nâng cao ý thức, trách nhiệm của nhân dân trước pháp luật  VTV24 - VTV24.md",
        "terms": ["Nguyễn Hải Long", "Quốc hội", "xử lý vi phạm hành chính", "phòng cháy chữa cháy", "kỷ cương",
                  "răn đe", "an ninh con người", "chung cư mini", "ngộ độc bánh mì", "ngân sách Nhà nước",
                  "chất độc da cam", "an toàn bức xạ", "hạt nhân", "nước ngầm", "phóng xạ", "niêm phong"],
    },
    "coso2": {
        "title": "Cơ sở 2 giảm tải bệnh viện tuyến Trung ương",
        "audio": "Cơ sở 2 giảm tải bệnh viện tuyến Trung ương  Cụm tin  VTV24 - VTV24.mp3",
        "ref": "Phụ đề _Cơ sở 2 giảm tải bệnh viện tuyến Trung ương  Cụm tin  VTV24 - VTV24.md",
        "terms": ["Nguyễn Văn Thắng", "EVN", "Bộ Công Thương", "Bộ Tài chính", "Bộ Tư pháp",
                  "thuế tiêu thụ đặc biệt", "giá bán lẻ điện", "Bệnh viện Nhi Trung ương", "Bạch Mai",
                  "Phụ sản Trung ương", "Ninh Bình", "nhồi máu cơ tim", "mạch vành", "bảo hiểm y tế",
                  "Tổ chức Y tế Thế giới", "tế bào gốc tạo máu", "ghép gan", "ghép thận", "mô tạng",
                  "Bộ Giáo dục và Đào tạo", "Ngữ văn", "dân tộc nội trú", "Núi Một", "Quy Nhơn", "Gia Lai",
                  "sạt lở"],
    },
    "thegioi": {
        "title": "Thế giới toàn cảnh ngày 26/10",
        "audio": "Thế giới toàn cảnh ngày 26_10 Iran tuyên bố không nhượng bộ nếu Mỹ và Israel tấn công trở lại - VTV24.mp3",
        "ref": "Phụ đề _Thế giới toàn cảnh ngày 26_10 Iran tuyên bố không nhượng bộ nếu Mỹ và Israel tấn công trở lại - VTV24.md",
        "terms": ["Brazil", "Lula", "Bolsonaro", "São Paulo", "Santa Catarina", "Mỹ Latinh", "Araghchi",
                  "Tehran", "Hormuz", "Donald Trump", "Pakistan", "Hamas", "Palestine", "Qatar", "Cheniere",
                  "Louisiana", "Texas", "Ras Laffan", "LNG", "Venezuela", "Caracas", "Babet", "Scotland",
                  "Amazon Web Services", "ASEAN", "Indonesia", "Malaysia", "Singapore", "Sydney", "Jetstar",
                  "Gold Coast", "Phúc Kiến", "Tỷ Quy", "Hồ Bắc", "Quảng Tây", "Thâm Quyến", "Thượng Hải",
                  "Bogotá", "Colombia", "Gwangju", "Washi", "Toyama", "Yatsuo", "Muromachi", "Meiji",
                  "kinh tế tầm thấp", "khí tự nhiên hóa lỏng", "drone"],
    },
}


def wer_parts(rw, hw):
    pairs = score.align(rw, hw)
    sub = sum(1 for i, j in pairs if i is not None and j is not None and rw[i] != hw[j])
    dele = sum(1 for i, j in pairs if j is None)
    ins = sum(1 for i, j in pairs if i is None)
    return pairs, sub, dele, ins


def term_scores(rw, hw, pairs, terms):
    """CER và tỉ lệ khớp đúng trên từng lần xuất hiện của thuật ngữ trong bản gỡ băng."""
    hyp_for_ref: list[list[int]] = [[] for _ in rw]
    last = 0
    for i, j in pairs:
        if i is not None:
            last = i
            if j is not None:
                hyp_for_ref[i].append(j)
        elif j is not None:
            hyp_for_ref[last].append(j)
    edits = chars = exact = total = 0
    per_term = {}
    for term in terms:
        tt = score.norm_tokens(term)
        k = len(tt)
        hit = cnt = 0
        for s in range(len(rw) - k + 1):
            if rw[s:s + k] != tt:
                continue
            js = sorted({j for i in range(s, s + k) for j in hyp_for_ref[i]})
            got = " ".join(hw[j] for j in js)
            want = " ".join(tt)
            edits += score.edit_distance(list(want), list(got))
            chars += len(want)
            cnt += 1
            hit += got == want
        if cnt:
            per_term[term] = (hit, cnt)
            exact += hit
            total += cnt
    return {"term_cer": edits / chars if chars else None, "term_exact": exact, "term_total": total,
            "per_term": per_term}


def speaker_scores(ref, hyp, pairs):
    matched = [(ref[i][0], hyp[j][0]) for i, j in pairs if i is not None and j is not None]
    rs = sorted({r for r, _ in matched})
    hs = sorted({h for _, h in matched}, key=lambda x: (x is None, x or ""))
    cm = np.zeros((len(rs), len(hs)), dtype=int)
    for r, h in matched:
        cm[rs.index(r), hs.index(h)] += 1
    real = [k for k, h in enumerate(hs) if h is not None]
    ri, hi = linear_sum_assignment(-cm[:, real])
    mapping = {rs[a]: hs[real[b]] for a, b in zip(ri, hi)}
    correct = sum(cm[a, real[b]] for a, b in zip(ri, hi))
    null = int(cm[:, hs.index(None)].sum()) if None in hs else 0
    purity = sum(cm[:, k].max() for k in real) / max(sum(cm[:, k].sum() for k in real), 1)
    return {"accuracy": correct / len(matched), "purity": purity, "aligned": len(matched), "null_words": null,
            "ref_speakers": len(rs), "hyp_speakers": len([h for h in hs if h is not None]),
            "mapping": mapping, "labels": [str(h) for h in hs], "rows": rs, "matrix": cm.tolist()}


def hallucinations(tr):
    found = []
    for s in tr["segments"]:
        text = s["text_raw"]
        dur = max((s["end_ms"] - s["start_ms"]) / 1000, 0.01)
        nwords = len(text.split())
        low = text.lower()
        if any(m in low for m in HALLUCINATION_MARKERS) or (nwords >= 6 and nwords / dur > 7):
            found.append({"start": s["start_ms"] / 1000, "dur": round(dur, 2), "text": text})
    return found


def is_flagged(seg) -> bool:
    """Câu bịa: nói nhanh quá sức người, hoặc chứa cụm kêu gọi đăng ký kênh."""
    text = seg["text_raw"]
    n = len(text.split())
    dur = max((seg["end_ms"] - seg["start_ms"]) / 1000, 0.01)
    return any(m in text.lower() for m in HALLUCINATION_MARKERS) or (n >= 4 and n / dur > MAX_WORDS_PER_SECOND)


def hyp_tokens(tr, drop_flagged: bool):
    out = []
    for seg in tr["segments"]:
        if drop_flagged and is_flagged(seg):
            continue
        words: list[list] = []
        for w in seg["words"]:
            # Whisper tách "150.000" thành "150" và ".000". Ghép lại trước khi đổi số thành chữ.
            if words and re.match(r"^[.,]\d{3}\b", w["text"]) and words[-1][1][-1:].isdigit():
                words[-1][1] += w["text"]
            else:
                words.append([w["speaker_label"], w["text"]])
        for label, text in words:
            out += [(label, t) for t in score.norm_tokens(text)]
    return out


def segment_stats(tr):
    durs = sorted((s["end_ms"] - s["start_ms"]) / 1000 for s in tr["segments"] if not is_flagged(s))
    texts = [s["text_raw"] for s in tr["segments"]]
    joined = " ".join(texts)
    letters = [ch for ch in joined if ch.isalpha()]
    return {
        "median_seg_s": durs[len(durs) // 2] if durs else 0,
        "max_seg_s": durs[-1] if durs else 0,
        "upper_ratio": sum(ch.isupper() for ch in letters) / max(len(letters), 1),
        "punct_per_100w": 100 * sum(joined.count(p) for p in ",.?!:;") / max(len(joined.split()), 1),
        "digit_tokens": sum(any(ch.isdigit() for ch in w) for w in joined.split()),
    }


def text_metrics(ref, hyp, terms):
    rw = [t for _, t in ref]
    hw = [t for _, t in hyp]
    pairs, sub, dele, ins = wer_parts(rw, hw)
    rc, hc = " ".join(rw), " ".join(hw)
    rwf = [t for t in rw if t not in FILLERS]
    hwf = [t for t in hw if t not in FILLERS]
    _, s2, d2, i2 = wer_parts(rwf, hwf)
    return pairs, {
        "hyp_words": len(hw), "wer": (sub + dele + ins) / len(rw), "sub": sub, "del": dele, "ins": ins,
        "cer": score.edit_distance(list(rc), list(hc)) / len(rc),
        "wer_nofill": (s2 + d2 + i2) / len(rwf),
        "cer_nofill": score.edit_distance(list(" ".join(rwf)), list(" ".join(hwf))) / len(" ".join(rwf)),
        "terms": term_scores(rw, hw, pairs, terms),
    }


def repeats(tr):
    """Câu liền nhau trùng nguyên văn, dấu hiệu lặp của Whisper hoặc trùng ở mép chunk."""
    out = []
    segs = tr["segments"]
    for a, b in zip(segs, segs[1:]):
        if a["text_raw"].strip() and a["text_raw"].strip().lower() == b["text_raw"].strip().lower():
            out.append({"start": b["start_ms"] / 1000, "text": b["text_raw"]})
    return out


def main():
    results = {}
    for run_dir in sorted((HERE / "runs").iterdir()):
        model = run_dir.name
        for clip, meta in CLIPS.items():
            hyp_path = run_dir / f"{clip}.json"
            if not hyp_path.exists():
                continue
            tr = json.load(open(hyp_path, encoding="utf-8"))
            run_meta = json.load(open(run_dir / f"{clip}.meta.json", encoding="utf-8"))
            ref = score.read_reference(str(DATA / meta["ref"]))
            rw = [t for _, t in ref]
            hyp = hyp_tokens(tr, drop_flagged=False)
            hyp_f = hyp_tokens(tr, drop_flagged=True)
            pairs, raw = text_metrics(ref, hyp, meta["terms"])
            pairs_f, filt = text_metrics(ref, hyp_f, meta["terms"])
            hw = [t for _, t in hyp_f]
            subs = Counter((rw[i], hw[j]) for i, j in pairs_f if i is not None and j is not None and rw[i] != hw[j])
            dels = Counter(rw[i] for i, j in pairs_f if j is None)
            r = {
                "ref_words": len(rw), "ref_speakers": len({s for s, _ in ref}),
                "raw": raw, "filtered": filt,
                "flagged_segments": [{"start": s["start_ms"] / 1000, "dur": round((s["end_ms"] - s["start_ms"]) / 1000, 2),
                                      "text": s["text_raw"]} for s in tr["segments"] if is_flagged(s)],
                "speakers": speaker_scores(ref, hyp_f, pairs_f),
                "repeats": repeats(tr),
                "seg_stats": segment_stats(tr),
                "top_subs": [[a, b, c] for (a, b), c in subs.most_common(30)],
                "top_dels": dels.most_common(15),
                "run": run_meta,
                "segments": len(tr["segments"]),
            }
            results.setdefault(model, {})[clip] = r
            print(f"{model:16} {clip:9} raw WER {raw['wer']:.2%} CER {raw['cer']:.2%} | filtered WER {filt['wer']:.2%} "
                  f"CER {filt['cer']:.2%} nofill {filt['wer_nofill']:.2%} termCER {filt['terms']['term_cer']:.2%} "
                  f"exact {filt['terms']['term_exact']}/{filt['terms']['term_total']} spk {r['speakers']['accuracy']:.2%} "
                  f"flagged {len(r['flagged_segments'])} time {run_meta['elapsed']}s")
    json.dump(results, open(HERE / "results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
