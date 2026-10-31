"""Chấm kết quả exp_decode.py."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate  # noqa: E402
import score  # noqa: E402

REFS = {"coso2": "coso2", "thegioi": "thegioi", "phapluat": "phapluat"}
out = {}
for path in sorted((HERE / "exp").glob("*.json")):
    name, cfg = path.stem.split("__")
    clip = REFS.get(name, "phapluat")
    meta = evaluate.CLIPS[clip]
    ref = score.read_reference(str(evaluate.DATA / meta["ref"]))
    tr = json.load(open(path, encoding="utf-8"))
    hyp = evaluate.hyp_tokens(tr, drop_flagged=False)
    hyp_f = evaluate.hyp_tokens(tr, drop_flagged=True)
    _, raw = evaluate.text_metrics(ref, hyp, meta["terms"])
    _, filt = evaluate.text_metrics(ref, hyp_f, meta["terms"])
    flagged = sum(evaluate.is_flagged(s) for s in tr["segments"])
    out.setdefault(name, {})[cfg] = {"wer": raw["wer"], "cer": raw["cer"], "wer_f": filt["wer"], "cer_f": filt["cer"],
                                     "sdi": (raw["sub"], raw["del"], raw["ins"]), "flagged": flagged,
                                     "time": tr["elapsed"], "chunks": tr["chunks"]}
    print(f"{name:12} {cfg:18} WER {raw['wer']:7.2%} CER {raw['cer']:7.2%} | lọc: WER {filt['wer']:7.2%} "
          f"S/D/I {raw['sub']}/{raw['del']}/{raw['ins']} bịa {flagged} chunks {tr['chunks']} {tr['elapsed']:.0f}s")
json.dump(out, open(HERE / "results_exp.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
