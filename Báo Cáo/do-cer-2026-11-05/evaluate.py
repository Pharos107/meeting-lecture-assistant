"""Chấm mọi cặp (bài, model) trong runs/ trên bộ "Data thực tế" và ghi results.json.

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

DATA = Path("E:/lehai/Documents/Project/STT/data/Data thực tế/ground_truth")
FILLERS = {"thì", "ấy", "ạ", "vâng", "dạ", "à", "ừ", "ờ", "ơ", "ừm", "cái"}
MAX_WORDS_PER_SECOND = 12
HALLUCINATION_MARKERS = ("subscribe", "la la school", "đăng ký kênh", "đăng kí kênh", "theo dõi kênh",
                         "cảm ơn các bạn đã theo dõi", "cảm ơn các bạn đã xem", "bỏ lỡ những video")

# Hai cách viết đều đúng trong tài liệu tiếng Việt. Quy về một dạng cho cả hai phía để không tính là lỗi.
VARIANTS = {
    "axit": "acid", "aldehyde": "aldehyd", "andehit": "aldehyd", "anđehit": "aldehyd", "andehyd": "aldehyd",
    "xeton": "ceton", "ketone": "ceton", "keton": "ceton", "ancol": "alcol", "alcohol": "alcol",
    "cacbon": "carbon", "clorua": "clorid", "chloride": "clorid", "chlorid": "clorid", "benzene": "benzen",
    "hidro": "hydro", "hiđro": "hydro", "amide": "amid", "benzoate": "benzoat", "oxi": "oxy", "este": "ester",
    "cacbonyl": "carbonyl", "cacboxylic": "carboxylic", "hiđrocacbon": "hydrocarbon", "hidrocacbon": "hydrocarbon",
    "okay": "ok", "oke": "ok", "nito": "nitơ", "phtalic": "phthalic", "quinone": "quinon",
}

CLIPS = {
    "quahat": {
        "title": "Quả và Hạt (phần 2), Thực vật Dược, UMP",
        "ref": "Quả và Hạt part 2 - PGS.TS Trương Thị Đẹp - Bài giảng Thực Vật Dược - Tài Liệu Dược Khoa UMP.md",
        "terms": ["alêron", "protid", "tinh bột", "nảy mầm", "phôi", "lá mầm", "nội nhũ", "ngoại nhũ", "vỏ hạt",
                  "vỏ quả", "họ Lúa", "quả dĩnh", "Cucurbitaceae", "Fabaceae", "Asteraceae", "rễ mầm", "thân mầm",
                  "chồi mầm", "tử diệp", "trụ dưới lá mầm", "hạt", "trưởng thành"],
    },
    "phoi21": {
        "title": "Phôi thai học phân tử và dị tật bẩm sinh (P1), ĐH Y Hà Nội",
        "ref": "2.1 - PHÔI THAI HỌC PHÂN TỬ VÀ DỊ TẬT BẨM SINH P1 - SDH Y HÀ NỘI - KIẾN THỨC Y HỌC - DI TRUYỀN - SẢN PHỤ KHOA.md",
        "terms": ["DNA", "RNA", "protein", "nucleotide", "histone", "apoptosis", "lipid", "acid amin", "amino acid",
                  "tế bào gốc", "phôi thai học", "dị tật bẩm sinh", "quái thai", "biệt hóa", "gen", "nhiễm sắc thể",
                  "phân bào", "tăng sinh", "di truyền", "thụ tinh", "hợp tử", "đột biến", "tín hiệu", "phân tử",
                  "phiên mã", "dịch mã", "biểu hiện gen", "WHO", "tế bào", "mô", "cơ quan"],
    },
    "phoi42": {
        "title": "Phôi thai học hệ tiêu hóa (4.2), ĐH Y Hà Nội",
        "ref": "4.2 - PHOI THAI HOC HE TIEU HOA - SDH 2025 YHN.md",
        # Bản gỡ băng ghi phần giảng tới câu "các bạn nghỉ khoảng 30 phút" (~13:40, đầu file ghi nhầm 07:35).
        # Phần sau là giờ giải lao, không chấm.
        "hyp_end_s": 830,
        "terms": ["đa ối", "nước ối", "thực quản", "hít sặc", "tá tràng", "hẹp tá tràng", "tịt tá tràng",
                  "hẹp môn vị bẩm sinh", "môn vị", "dạ dày", "khí quản", "rò khí quản", "gan", "đường dẫn mật",
                  "hỗng tràng", "hồi tràng", "ống tiêu hóa", "siêu âm", "chẩn đoán hình ảnh", "nôn", "dị tật",
                  "bẩm sinh", "nội bì", "trung bì", "mạc treo", "phì đại", "tắc", "hẹp"],
    },
    "aldehyd": {
        "title": "Aldehyd – Ceton (phần 1), Hóa hữu cơ 1, UMP",
        "ref": "Aldehyd - Ceton phần 1 - Bài giảng hóa hữu cơ 1 - Tài Liệu Dược Khoa UMP.md",
        "terms": ["aldehyd", "ceton", "quinon", "carbonyl", "hydrocarbon", "carbon", "alcol", "formyl",
                  "carbaldehyd", "propanal", "propenal", "acrolein", "benzaldehyd", "IUPAC", "carboxylic", "acid",
                  "liên hợp", "nhóm chức", "danh pháp", "tiếp vĩ ngữ", "tiếp đầu ngữ", "hydroxy", "oxo", "amino",
                  "amin", "pentanol", "propionic", "acrylic", "benzoic", "liên kết pi", "acyl", "benzen",
                  "propionaldehyd", "ethanol", "cycloalkan", "mạch chính", "nhóm thế"],
    },
    "acid": {
        "title": "Bài tập acid đơn chức và dẫn xuất (phần 2), Hóa hữu cơ 1, UMP",
        "ref": "Bài tập acid đơn chức và dẫn xuất phần 2 - Hóa hữu cơ 1 - UMP.md",
        "terms": ["acid", "benzoic", "acetamido", "carbamoyl", "benzamid", "amid", "sulfamoyl", "benzoat",
                  "phthalic", "pyrrolidin", "benzoyl", "clorid", "ester", "phenoxy", "amoni", "ethyl", "acetyl",
                  "phthalimid", "anhydrid", "benzyl", "brom", "gallic", "salicylic", "methoxy", "phenyl",
                  "methylcarbamoyl", "pentyl", "toluic", "propionic", "nitơ", "alphabet", "dẫn xuất", "halogenid",
                  "natri benzoat", "benzonitril", "formyl", "oxo", "amino", "hydro", "carbon", "para", "meta", "ortho"],
    },
    "hop1": {
        "title": "Kỹ năng điều hành cuộc họp (lớp đào tạo, 28 phút)",
        "ref": "VideoMetting_1_28p.md",
        "terms": ["brainstorming", "power", "cuộc họp", "ra quyết định", "đồng thuận", "chủ trì", "thư ký",
                  "biên bản", "kết luận", "chương trình", "lãnh đạo", "quyền lực", "tổ chức", "mục tiêu", "tập thể",
                  "happy hour", "hiệu quả", "lãng phí", "bình đẳng", "con người", "công việc", "ma trận"],
    },
    "hop2": {
        "title": "Họp giao ban phòng marketing (14 phút)",
        "ref": "VideoMetting_2_14p.md",
        "terms": ["marketing", "banner", "target", "tour", "file", "online", "digital", "blog", "facebook",
                  "internet", "video", "traffic", "mail", "doanh số", "khách hàng", "kế hoạch", "du lịch",
                  "ngân sách", "báo cáo", "thiết kế", "chiến dịch", "quảng cáo", "giám đốc", "trưởng phòng"],
    },
}


def norm_tokens(text: str) -> list[str]:
    return [VARIANTS.get(t, t) for t in score.norm_tokens(text)]


def read_reference(path: Path) -> list[tuple[str, str]]:
    """Trả danh sách (người nói, token). Bỏ phần đầu, tên người nói, ghi chú *(...)* cả dòng lẫn giữa câu."""
    lines = open(path, encoding="utf-8").read().splitlines()
    start = next(k for k, line in enumerate(lines) if line.startswith("### PHẦN"))
    speaker = None
    out = []
    for line in lines[start:]:
        s = line.strip()
        if not s or s == "---" or s.startswith("#") or re.fullmatch(r"\*\(.*\)\*", s):
            continue
        m = re.fullmatch(r"\*\*(.+?):\*\*", s)
        if m:
            speaker = m.group(1)
            continue
        s = re.sub(r"\*\([^)]*\)\*", " ", s)
        s = re.sub(r"^(\d+\.|-)\s+", "", s).replace("**", "")
        out += [(speaker, t) for t in norm_tokens(s)]
    return out


def is_flagged(seg) -> bool:
    """Câu bịa còn sót: nói nhanh quá sức người, hoặc chứa cụm kêu gọi đăng ký kênh."""
    text = seg["text_raw"]
    n = len(text.split())
    dur = max((seg["end_ms"] - seg["start_ms"]) / 1000, 0.01)
    return any(m in text.lower() for m in HALLUCINATION_MARKERS) or (n >= 4 and n / dur > MAX_WORDS_PER_SECOND)


def hyp_tokens(tr, end_s=None):
    """Trả danh sách (người nói, token, giây bắt đầu)."""
    out = []
    for seg in tr["segments"]:
        words: list[list] = []
        for w in seg["words"]:
            if end_s is not None and w["start_ms"] / 1000 > end_s:
                continue
            # Whisper tách "150.000" thành "150" và ".000". Ghép lại trước khi đổi số thành chữ.
            if words and re.match(r"^[.,]\d{3}\b", w["text"]) and words[-1][1][-1:].isdigit():
                words[-1][1] += w["text"]
            else:
                words.append([w["speaker_label"], w["text"], w["start_ms"] / 1000])
        for label, text, t0 in words:
            out += [(label, t, t0) for t in norm_tokens(text)]
    return out


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
        tt = norm_tokens(term)
        k = len(tt)
        hit = cnt = 0
        misses = Counter()
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
            if got != want:
                misses[got or "∅"] += 1
        if cnt:
            per_term[term] = {"hit": hit, "n": cnt, "misses": misses.most_common(4)}
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


def runs_of(pairs, kind, rw, hw, htime, min_len=12):
    """Các đoạn liền nhau toàn chèn (kind='ins') hoặc toàn mất (kind='del'), kèm mốc thời gian gần nhất."""
    out, cur, last_t = [], [], 0.0
    for i, j in pairs:
        if j is not None:
            last_t = htime[j]
        hit = (i is None) if kind == "ins" else (j is None)
        if hit:
            cur.append((i, j, last_t))
            continue
        if len(cur) >= min_len:
            out.append(cur)
        cur = []
    if len(cur) >= min_len:
        out.append(cur)
    res = []
    for c in out:
        toks = [hw[j] for _, j, _ in c] if kind == "ins" else [rw[i] for i, _, _ in c]
        res.append({"t": round(c[0][2], 1), "n": len(c), "text": " ".join(toks[:40])})
    return res


def segment_stats(tr):
    durs = sorted((s["end_ms"] - s["start_ms"]) / 1000 for s in tr["segments"])
    joined = " ".join(s["text_raw"] for s in tr["segments"])
    letters = [ch for ch in joined if ch.isalpha()]
    return {
        "median_seg_s": durs[len(durs) // 2] if durs else 0,
        "max_seg_s": durs[-1] if durs else 0,
        "upper_ratio": sum(ch.isupper() for ch in letters) / max(len(letters), 1),
        "punct_per_100w": 100 * sum(joined.count(p) for p in ",.?!:;") / max(len(joined.split()), 1),
        "digit_tokens": sum(any(ch.isdigit() for ch in w) for w in joined.split()),
    }


def max_gap(tr, end_s=None):
    """Khoảng trống dài nhất giữa hai từ liên tiếp (giây) và vị trí."""
    ts = sorted((w["start_ms"] / 1000, w["end_ms"] / 1000) for s in tr["segments"] for w in s["words"]
                if end_s is None or w["start_ms"] / 1000 <= end_s)
    gaps = sorted(((b[0] - a[1], a[1]) for a, b in zip(ts, ts[1:])), reverse=True)
    return [[round(g, 1), round(t, 1)] for g, t in gaps[:5]]


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
            vram = [int(x) for x in open(run_dir / f"{clip}.vram").read().split() if x.isdigit()]
            end_s = meta.get("hyp_end_s")
            ref = read_reference(DATA / meta["ref"])
            hyp = hyp_tokens(tr, end_s)
            rw = [t for _, t in ref]
            hw = [t for _, t, _ in hyp]
            ht = [t0 for _, _, t0 in hyp]
            pairs, sub, dele, ins = wer_parts(rw, hw)
            rc, hc = " ".join(rw), " ".join(hw)
            rwf = [t for t in rw if t not in FILLERS]
            hwf = [t for t in hw if t not in FILLERS]
            _, s2, d2, i2 = wer_parts(rwf, hwf)
            subs = Counter((rw[i], hw[j]) for i, j in pairs if i is not None and j is not None and rw[i] != hw[j])
            r = {
                "ref_words": len(rw), "hyp_words": len(hw), "ref_speakers": len({s for s, _ in ref}),
                "wer": (sub + dele + ins) / len(rw), "sub": sub, "del": dele, "ins": ins,
                "cer": score.edit_distance(list(rc), list(hc)) / len(rc),
                "wer_nofill": (s2 + d2 + i2) / len(rwf),
                "terms": term_scores(rw, hw, pairs, meta["terms"]),
                "speakers": speaker_scores(ref, [(a, b) for a, b, _ in hyp], pairs),
                "flagged_segments": [{"start": s["start_ms"] / 1000,
                                      "dur": round((s["end_ms"] - s["start_ms"]) / 1000, 2), "text": s["text_raw"]}
                                     for s in tr["segments"] if is_flagged(s)],
                "ins_runs": runs_of(pairs, "ins", rw, hw, ht),
                "del_runs": runs_of(pairs, "del", rw, hw, ht),
                "max_gaps": max_gap(tr, end_s),
                "seg_stats": segment_stats(tr),
                "segments": len(tr["segments"]),
                "top_subs": [[a, b, c] for (a, b), c in subs.most_common(40)],
                "run": run_meta,
                "peak_vram_mib": max(vram) if vram else None,
            }
            results.setdefault(model, {})[clip] = r
            print(f"{model:16} {clip:8} WER {r['wer']:6.2%} CER {r['cer']:6.2%} nofill {r['wer_nofill']:6.2%} "
                  f"(S{sub} D{dele} I{ins}) termCER {r['terms']['term_cer'] or 0:6.2%} "
                  f"exact {r['terms']['term_exact']}/{r['terms']['term_total']} spk {r['speakers']['accuracy']:.1%} "
                  f"({r['speakers']['ref_speakers']}/{r['speakers']['hyp_speakers']}) flagged {len(r['flagged_segments'])} "
                  f"time {run_meta['elapsed']}s VRAM {r['peak_vram_mib']}", flush=True)
    json.dump(results, open(HERE / "results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
