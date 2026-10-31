"""Ráp báo cáo từ khung và các file raw output."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
target = Path(sys.argv[1])
text = (HERE / "report_template.md").read_text(encoding="utf-8")

text = re.sub(r"\{\{RAW:([^}]+)\}\}", lambda m: (HERE / m.group(1)).read_text(encoding="utf-8").rstrip("\n"), text)

excerpts = (HERE / "excerpts.md").read_text(encoding="utf-8")
cut = excerpts.index("#### `babble_")
text = text.replace("{{EXCERPTS_MODELS}}", excerpts[:cut].rstrip())
text = text.replace("{{EXCERPTS_NOISE}}", excerpts[cut:].rstrip())

groups = [
    ("So sánh hai model", [("large-v3-turbo", HERE / "runs" / "large-v3-turbo"), ("PhoWhisper-large", HERE / "runs" / "phowhisper-large")],
     ["phapluat", "coso2", "thegioi"]),
    ("large-v3-turbo sau khi sửa", [("large-v3-turbo, sau sửa", HERE / "runs_fixed" / "large-v3-turbo")],
     ["phapluat", "coso2", "thegioi", "babble_10db", "babble_5db", "pink_5db", "pink_0db"]),
    ("Bản nhiễu, large-v3-turbo trước khi sửa", [("large-v3-turbo, trước sửa", HERE / "runs_noise" / "large-v3-turbo")],
     ["pink_20db", "pink_10db", "pink_5db", "pink_0db", "babble_20db", "babble_10db", "babble_5db", "babble_0db"]),
]
blocks = []
for title, runs, names in groups:
    blocks.append(f"### {title}\n")
    for label, folder in runs:
        for name in names:
            log = (folder / f"{name}.log").read_text(encoding="utf-8").rstrip("\n")
            blocks.append(f"<details>\n<summary><code>{name}</code> — {label}</summary>\n\n```text\n{log}\n```\n\n</details>\n")
text = text.replace("{{RUNLOGS}}", "\n".join(blocks))

assert "{{" not in text, re.findall(r"\{\{[^}]+\}\}", text)
target.write_text(text, encoding="utf-8")
print("written", target, len(text), "chars")
