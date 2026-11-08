import glob, json, zlib, sys
def ratio(text):
    b = text.encode("utf-8")
    return len(b) / len(zlib.compress(b)) if b else 0
roots = ["C:/Users/lehai/AppData/Local/Temp/claude/E--lehai-Documents-Project-STT/*/scratchpad/runs/*/*.json", sys.argv[1] + "/runs/*/*.json"]
rows = []
for pattern in roots:
    for p in glob.glob(pattern):
        if p.endswith(".meta.json"): continue
        for s in json.load(open(p, encoding="utf-8"))["segments"]:
            rows.append((ratio(s["text_raw"]), "/".join(p.replace("\\", "/").split("/")[-2:]), s["start_ms"] / 1000, s["text_raw"]))
rows.sort(reverse=True)
print("câu", len(rows), "> 2.4:", sum(1 for r in rows if r[0] > 2.4), "> 2.0:", sum(1 for r in rows if r[0] > 2.0))
for r in rows[:15]:
    print(f"{r[0]:.2f} {r[1]} {r[2]:.0f}s {r[3][:110]}")
