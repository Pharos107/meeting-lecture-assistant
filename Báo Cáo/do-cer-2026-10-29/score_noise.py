"""Chấm các bản trộn nhiễu của bài phapluat. Bản sạch là runs/large-v3-turbo/phapluat.json."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate  # noqa: E402
import score  # noqa: E402

meta = evaluate.CLIPS["phapluat"]
ref = score.read_reference(str(evaluate.DATA / meta["ref"]))
clean_chunks = json.load(open(HERE / "chunks.json", encoding="utf-8"))["phapluat"]
noise_chunks = json.load(open(HERE / "chunks_noise.json", encoding="utf-8"))
truth = [(a, b) for a, b, _ in clean_chunks["regions"]]


def overlap(a, b, regions):
    return sum(max(0.0, min(b, y) - max(a, x)) for x, y in regions)


def speech_without_text(tr, regions):
    spans = sorted((w["start_ms"] / 1000 - 0.5, w["end_ms"] / 1000 + 0.5)
                   for s in tr["segments"] if not evaluate.is_flagged(s) for w in s["words"])
    total = 0.0
    for a, b in regions:
        cur = a
        for x, y in spans:
            if y < cur or x > b:
                continue
            if x > cur and x - cur >= 1.5:
                total += min(x, b) - cur
            cur = max(cur, y)
            if cur >= b:
                break
        if b - cur >= 1.5:
            total += b - cur
    return total


rows = [("sạch", HERE / "runs" / "large-v3-turbo" / "phapluat.json", truth)]
for kind in ["pink", "babble"]:
    for snr in [20, 10, 5, 0]:
        name = f"{kind}_{snr}db"
        regs = [(a, b) for a, b, _ in noise_chunks[name]["regions"]]
        rows.append((name, HERE / "runs_noise" / "large-v3-turbo" / f"{name}.json", regs))

speech = sum(b - a for a, b in truth)
print(f"{'bản':12} {'WER':>7} {'CER':>7} {'WERlọc':>7} {'CERlọc':>7} {'thay/mất/chèn':>14} {'câu bịa':>7} "
      f"{'VAD bắt':>8} {'VAD thừa':>8} {'tiếng không chữ':>15} {'người':>6} {'gán đúng':>8} {'thời gian':>9}")
out = {}
for name, path, regs in rows:
    tr = json.load(open(path, encoding="utf-8"))
    hyp = evaluate.hyp_tokens(tr, drop_flagged=False)
    hyp_f = evaluate.hyp_tokens(tr, drop_flagged=True)
    _, raw = evaluate.text_metrics(ref, hyp, meta["terms"])
    pairs_f, filt = evaluate.text_metrics(ref, hyp_f, meta["terms"])
    spk = evaluate.speaker_scores(ref, hyp_f, pairs_f)
    flagged = [s["text_raw"] for s in tr["segments"] if evaluate.is_flagged(s)]
    vad_hit = sum(overlap(a, b, regs) for a, b in truth) / speech
    vad_extra = sum(b - a for a, b in regs) - sum(overlap(a, b, truth) for a, b in regs)
    swt = speech_without_text(tr, truth)
    meta_path = path.with_name(path.stem + ".meta.json")
    elapsed = json.load(open(meta_path, encoding="utf-8"))["elapsed"] if meta_path.exists() else None
    out[name] = {"raw": raw, "filtered": filt, "flagged": flagged, "vad_hit": vad_hit, "vad_extra": vad_extra,
                 "speech_without_text": swt, "speakers": spk["hyp_speakers"], "spk_acc": spk["accuracy"],
                 "elapsed": elapsed}
    print(f"{name:12} {raw['wer']:7.2%} {raw['cer']:7.2%} {filt['wer']:7.2%} {filt['cer']:7.2%} "
          f"{filt['sub']:4}/{filt['del']:4}/{filt['ins']:4} {len(flagged):7} {vad_hit:8.1%} {vad_extra:7.1f}s "
          f"{swt:8.1f}s ({swt / speech:4.1%}) {spk['hyp_speakers']:6} {spk['accuracy']:8.1%} {elapsed}")
    for t in flagged[:3]:
        print("      bịa:", t[:100])
json.dump(out, open(HERE / "results_noise.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
