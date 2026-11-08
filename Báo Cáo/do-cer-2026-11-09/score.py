"""Chấm transcript của job so với bản gỡ băng markdown có tên người nói.

Dùng: python score.py <phụ đề.md> <transcript.json> [file báo cáo chi tiết]
"""
import json
import re
import sys
import unicodedata
from collections import Counter

import numpy as np
from scipy.optimize import linear_sum_assignment

DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]


def read3(n: int, full: bool) -> list[str]:
    h, t, u = n // 100, n // 10 % 10, n % 10
    out: list[str] = []
    if full or h:
        out += [DIGITS[h], "trăm"]
    if t == 0:
        if u and (full or h):
            out.append("lẻ")
        if u:
            out.append(DIGITS[u])
        return out
    out += ["mười"] if t == 1 else [DIGITS[t], "mươi"]
    if u == 1 and t > 1:
        out.append("mốt")
    elif u == 5:
        out.append("lăm")
    elif u == 4 and t > 1:
        out.append("tư")
    elif u:
        out.append(DIGITS[u])
    return out


def num_words(n: int) -> list[str]:
    if n == 0:
        return ["không"]
    groups = []
    while n:
        groups.append(n % 1000)
        n //= 1000
    units = ["", "nghìn", "triệu", "tỷ"]
    out: list[str] = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g == 0:
            continue
        out += read3(g, full=i < len(groups) - 1)
        if units[i]:
            out.append(units[i])
    return out


_TONES = "̣́̀̉̃"
_OLD_TONE = re.compile(rf"(?<!q)([ou])([aey])([{_TONES}])$")


def new_tone_style(tok: str) -> str:
    """Đưa kiểu bỏ dấu cũ (hoá, thoả, thuỷ) về kiểu mới (hóa, thỏa, thủy). Giữ nguyên quý."""
    d = unicodedata.normalize("NFD", tok)
    return unicodedata.normalize("NFC", _OLD_TONE.sub(r"\1\3\2", d))


def norm_tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).lower()
    text = text.replace("–", " ").replace("-", " ").replace("%", " phần trăm ")
    # Pipeline ghép từ bằng dấu cách nên "150.000" thành "150 .000". Ghép lại để không tính lỗi này cho model.
    text = re.sub(r"(\d) ([.,]\d{3})\b", r"\1\2", text)
    text = re.sub(r"(\d)[.,](\d{3})\b", r"\1\2", text)
    text = re.sub(r"[^\w\s]", " ", text)
    out: list[str] = []
    for tok in text.split():
        out += num_words(int(tok)) if tok.isdigit() and len(tok) < 13 else [new_tone_style(tok)]
    return out


def read_reference(path: str) -> list[tuple[str, str]]:
    """Trả danh sách (người nói, token) theo thứ tự."""
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
        s = re.sub(r"^(\d+\.|-)\s+", "", s).replace("**", "")
        out += [(speaker, t) for t in norm_tokens(s)]
    return out


def read_hypothesis(path: str) -> list[tuple[str | None, str]]:
    tr = json.load(open(path, encoding="utf-8"))
    out = []
    for seg in tr["segments"]:
        for w in seg["words"]:
            out += [(w["speaker_label"], t) for t in norm_tokens(w["text"])]
    return out


def edit_distance(a: list, b: list) -> int:
    """Levenshtein theo hàng, vectơ hóa bằng numpy."""
    if not a:
        return len(b)
    ids = {x: i for i, x in enumerate(set(a) | set(b))}
    av = np.array([ids[x] for x in a])
    bv = np.array([ids[x] for x in b])
    prev = np.arange(len(b) + 1)
    ar = np.arange(len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = np.empty_like(prev)
        cur[0] = i
        cur[1:] = np.minimum(prev[1:] + 1, prev[:-1] + (bv != av[i - 1]))
        cur = np.minimum.accumulate(cur - ar) + ar
        prev = cur
    return int(prev[-1])


def align(a: list[str], b: list[str]) -> list[tuple[int | None, int | None]]:
    """Căn từng từ, trả các cặp chỉ số (ref, hyp); None là chèn hoặc xóa."""
    n, m = len(a), len(b)
    d = np.zeros((n + 1, m + 1), dtype=np.int32)
    d[:, 0] = np.arange(n + 1)
    d[0, :] = np.arange(m + 1)
    ar = np.arange(m + 1)
    for i in range(1, n + 1):
        sub = np.array([x != a[i - 1] for x in b], dtype=np.int32)
        row = np.empty(m + 1, dtype=np.int32)
        row[0] = i
        row[1:] = np.minimum(d[i - 1, 1:] + 1, d[i - 1, :-1] + sub)
        d[i] = np.minimum.accumulate(row - ar) + ar
    pairs = []
    i, j = n, m
    while i or j:
        if i and j and d[i, j] == d[i - 1, j - 1] + (a[i - 1] != b[j - 1]):
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and d[i, j] == d[i - 1, j] + 1:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    return pairs[::-1]


def main() -> None:
    ref = read_reference(sys.argv[1])
    hyp = read_hypothesis(sys.argv[2])
    rw = [t for _, t in ref]
    hw = [t for _, t in hyp]

    pairs = align(rw, hw)
    sub = sum(1 for i, j in pairs if i is not None and j is not None and rw[i] != hw[j])
    dele = sum(1 for i, j in pairs if j is None)
    ins = sum(1 for i, j in pairs if i is None)
    wer = (sub + dele + ins) / len(rw)
    rc, hc = " ".join(rw), " ".join(hw)
    cer = edit_distance(list(rc), list(hc)) / len(rc)
    print(f"ref words {len(rw)}  hyp words {len(hw)}")
    print(f"WER {wer:.2%}  (sub {sub}, del {dele}, ins {ins})")
    print(f"CER {cer:.2%}")

    # Người nói: chỉ tính các cặp từ đã căn được.
    matched = [(ref[i][0], hyp[j][0]) for i, j in pairs if i is not None and j is not None]
    rs = sorted({r for r, _ in matched})
    hs = sorted({h for _, h in matched}, key=lambda x: (x is None, x or ""))
    cm = np.zeros((len(rs), len(hs)), dtype=int)
    for r, h in matched:
        cm[rs.index(r), hs.index(h)] += 1
    ri, hi = linear_sum_assignment(-cm)
    mapping = {rs[a]: hs[b] for a, b in zip(ri, hi)}
    correct = sum(cm[a, b] for a, b in zip(ri, hi))
    print(f"speaker word accuracy {correct / len(matched):.2%} over {len(matched)} aligned words")
    print("hyp labels:", hs)
    header = "".join(f"{str(h):>12}" for h in hs)
    print(f"{'':24}{header}")
    for a, r in enumerate(rs):
        print(f"{r:24}" + "".join(f"{v:>12}" for v in cm[a]) + f"   -> {mapping.get(r)}")

    if len(sys.argv) > 3:
        subs = Counter((rw[i], hw[j]) for i, j in pairs if i is not None and j is not None and rw[i] != hw[j])
        with open(sys.argv[3], "w", encoding="utf-8") as f:
            f.write("Top substitutions (ref -> hyp):\n")
            for (r, h), c in subs.most_common(60):
                f.write(f"{c:3} {r} -> {h}\n")
            f.write("\nDeleted ref words:\n")
            f.write(" ".join(rw[i] for i, j in pairs if j is None) + "\n")
            f.write("\nInserted hyp words:\n")
            f.write(" ".join(hw[j] for i, j in pairs if i is None) + "\n")
            f.write("\nAlignment (ref|hyp), errors in [..]:\n")
            line = []
            for i, j in pairs:
                r = rw[i] if i is not None else "*"
                h = hw[j] if j is not None else "*"
                line.append(r if r == h else f"[{r}|{h}]")
            f.write(" ".join(line) + "\n")


if __name__ == "__main__":
    main()
