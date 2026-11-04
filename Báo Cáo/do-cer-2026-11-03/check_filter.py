import glob, json
from app.services.stt_engine import is_hallucination
total = 0
for p in sorted(glob.glob("/runs/*/*.json")):
    if p.endswith(".meta.json"):
        continue
    for s in json.load(open(p, encoding="utf-8"))["segments"]:
        total += 1
        if is_hallucination(s["text_raw"]):
            print(p.split("/runs/")[1], round(s["start_ms"] / 1000, 1), s["text_raw"])
print("segments checked", total)
