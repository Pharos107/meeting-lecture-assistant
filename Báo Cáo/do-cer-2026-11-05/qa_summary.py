"""Số tổng hợp của #23 từ qa_out.json và qa_grades.json.

Dùng: python -I -X utf8 qa_summary.py > raw-logs/qa_summary.txt
Giá gemini-3.5-flash-lite (bảng giá Gemini Developer API, 2026-11-05): 0,30 USD/1M token vào, 2,50 USD/1M token ra.
Lần gọi thẳng bị 503 thì lấy prompt_tokens trung bình của cùng bản ghi và completion_tokens trung vị của bản ghi đó.
"""
import json
import statistics
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRICE_IN, PRICE_OUT = 0.30e-6, 2.50e-6
out = json.load(open(HERE / "qa_out.json", encoding="utf-8"))
grades = json.load(open(HERE / "qa_grades.json", encoding="utf-8"))["answers"]

by_kind = {"answerable": Counter(), "unanswerable": Counter()}
for a in out["answers"]:
    by_kind[a["kind"]][grades[a["id"]]["grade"]] += 1
for kind, c in by_kind.items():
    print(kind, dict(c), "tổng", sum(c.values()))
total = sum(sum(c.values()) for c in by_kind.values())
right = sum(c["đúng"] for c in by_kind.values())
print(f"đúng {right}/{total} = {right / total:.0%}")
print("bịa", sum(g["fabricated"] for g in grades.values()))
ok = sum(g["stamps_ok"] for g in grades.values())
bad = sum(g["stamps_bad"] for g in grades.values())
ans_ids = {a["id"] for a in out["answers"] if a["kind"] == "answerable"}
ok_a = sum(grades[i]["stamps_ok"] for i in ans_ids)
bad_a = sum(grades[i]["stamps_bad"] for i in ans_ids)
print(f"mốc đúng {ok}/{ok + bad} = {ok / (ok + bad):.0%}; riêng câu có đáp án {ok_a}/{ok_a + bad_a} = {ok_a / (ok_a + bad_a):.0%}")

ttft = [a["ttft_s"] for a in out["answers"] if a["ttft_s"] is not None]
tot = [a["total_s"] for a in out["answers"]]
q = statistics.quantiles(ttft, n=10)
print(f"chữ đầu tiên: trung vị {statistics.median(ttft):.2f}s, p90 {q[-1]:.2f}s, min {min(ttft):.2f}s, max {max(ttft):.2f}s")
print(f"trọn câu: trung vị {statistics.median(tot):.2f}s, max {max(tot):.2f}s")

for clip in sorted({a["clip"] for a in out["answers"]}):
    rows = [a for a in out["answers"] if a["clip"] == clip]
    known = [a["usage"] for a in rows if a["usage"].get("prompt_tokens")]
    p_mean = statistics.mean(u["prompt_tokens"] for u in known)
    c_med = statistics.median(u["completion_tokens"] for u in known)
    costs = []
    for a in rows:
        u = a["usage"]
        p = u.get("prompt_tokens") or p_mean
        c = u.get("completion_tokens") or c_med
        costs.append(p * PRICE_IN + c * PRICE_OUT)
    comps = [u["completion_tokens"] for u in known]
    print(f"{clip}: {len(rows)} câu, prompt ~{p_mean:.0f} token, completion {min(comps)}–{max(comps)} (trung vị {c_med:.0f}), "
          f"chi phí mỗi câu trung bình {statistics.mean(costs) * 1000:.2f}‰ USD, tổng {sum(costs):.4f} USD")
