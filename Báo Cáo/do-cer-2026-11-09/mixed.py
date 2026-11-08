"""Đếm câu có từ mang từ hai nhãn người nói thật trở lên (bỏ từ null), cho mỗi transcript trong các thư mục."""
import glob
import json
import sys

for folder in sys.argv[1:]:
    for path in sorted(glob.glob(folder + "/*.json")):
        if path.endswith(".meta.json"):
            continue
        segments = json.load(open(path, encoding="utf-8"))["segments"]
        mixed = 0
        null_mixed = 0
        for s in segments:
            labels = {w["speaker_label"] for w in s["words"]}
            if len(labels - {None}) > 1:
                mixed += 1
            if None in labels and len(labels) > 1:
                null_mixed += 1
        speakers = {s["speaker_label"] for s in segments} - {None}
        name = path.replace("\\", "/").split("/")[-2:]
        print(f"{'/'.join(name):45} câu {len(segments):5} người nói {len(speakers)} "
              f"lẫn hai nhãn thật {mixed:4} có từ null {null_mixed:4}")
