import glob, json, sys
sys.path.insert(0, ".")
from app.services import stt_engine as e
root = "C:/Users/lehai/AppData/Local/Temp/claude/E--lehai-Documents-Project-STT"
files = [p for p in glob.glob(root + "/*/scratchpad/runs/*/*.json") if not p.endswith(".meta.json")]
total = 0
lengths = []
for p in sorted(files):
    for s in json.load(open(p, encoding="utf-8"))["segments"]:
        total += 1
        plain = e._plain(s["text_raw"])
        n = len(plain.split())
        lengths.append(n)
        padded = f" {plain} "
        hits = [ph for ph in e._CALL_TO_ACTION_PLAIN if f" {ph} " in padded]
        if hits or "kênh" in plain or "subscribe" in plain or "video" in plain:
            print(p.replace("\\","/").split("/runs/")[1], round(s["start_ms"]/1000,1), n, hits, s["text_raw"][:160])
print("files", len(files), "segments", total)
import statistics
lengths.sort()
print("words median", statistics.median(lengths), "p90", lengths[int(.9*len(lengths))], "max", lengths[-1], ">20:", sum(1 for x in lengths if x > 20), ">30:", sum(1 for x in lengths if x > 30))
