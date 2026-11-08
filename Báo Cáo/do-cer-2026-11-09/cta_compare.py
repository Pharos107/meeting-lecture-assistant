import glob, json, sys, importlib.util
sys.path.insert(0, ".")
from app.services import stt_engine as new
S = sys.argv[1]
spec = importlib.util.spec_from_file_location("old", S + "/stt_engine_old.py"); old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
root = "C:/Users/lehai/AppData/Local/Temp/claude/E--lehai-Documents-Project-STT"
files = sorted(p for p in glob.glob(root + "/*/scratchpad/runs/*/*.json") if not p.endswith(".meta.json"))
n = 0
for p in files:
    for s in json.load(open(p, encoding="utf-8"))["segments"]:
        n += 1
        a, b = old.is_hallucination(s["text_raw"]), new.is_hallucination(s["text_raw"])
        if a != b:
            print("DIFF", p.replace("\\", "/").split("/runs/")[1], round(s["start_ms"] / 1000, 1), a, "->", b, s["text_raw"][:140])
extra = ["Cảm ơn các bạn đã theo dõi và hãy subscribe cho kênh lalaschool Để không bỏ lỡ những video hấp dẫn",
         "Các bạn hãy đăng kí cho kênh lalaschool Để không bỏ lỡ những video hấp dẫn nó tiếp tục thể hiện năng lực sẽ trở thành công thức"]
for t in extra:
    print(len(new._plain(t).split()), new._uncovered_words(new._plain(t).split()), old.is_hallucination(t), new.is_hallucination(t), t[:80])
print("segments", n, "files", len(files))
