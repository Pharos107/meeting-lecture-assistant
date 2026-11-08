import glob, json, sys
sys.path.insert(0, ".")
from app.services.stt_engine import is_hallucination, trim_call_to_action
roots = ["C:/Users/lehai/AppData/Local/Temp/claude/E--lehai-Documents-Project-STT/*/scratchpad/runs/*/*.json", sys.argv[1] + "/runs/*/*.json"]
n = 0
for pattern in roots:
    for p in sorted(glob.glob(pattern)):
        if p.endswith(".meta.json"):
            continue
        for s in json.load(open(p, encoding="utf-8"))["segments"]:
            n += 1
            if is_hallucination(s["text_raw"]):
                continue
            words = [{"text": w["text"]} for w in s["words"]] or [{"text": t} for t in s["text_raw"].split()]
            kept = trim_call_to_action(words)
            if len(kept) != len(words):
                name = "/".join(p.replace("\\", "/").split("/")[-2:])
                print(f"{name} {s['start_ms']/1000:.1f}: {len(words)} -> {len(kept)} từ")
                print("   cũ:", s["text_raw"][:150])
                print("   giữ:", " ".join(w["text"] for w in kept)[:150])
print("câu", n)
