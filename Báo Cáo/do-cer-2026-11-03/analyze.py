import json, sys
sys.path.insert(0, '.')
import evaluate as E, score
R = json.load(open('results.json', encoding='utf-8'))
T, P = R['large-v3-turbo'], R['phowhisper-large']
# 1. hop1: overlap of insertion runs
def spans(r): return [(x['t'], x['t'] + x['n'] / 3.0, x['n']) for x in r['ins_runs']]
for clip in ['hop1']:
    a, b = spans(T[clip]), spans(P[clip])
    shared = sum(n for s, e, n in a if any(s2 < e + 15 and s < e2 + 15 for s2, e2, _ in b))
    print(clip, 'turbo ins-run words', sum(n for *_, n in a), 'shared with pho', shared, '| pho ins-run words', sum(n for *_, n in b))
    print(' hyp words turbo', T[clip]['hyp_words'], 'pho', P[clip]['hyp_words'], 'ref', T[clip]['ref_words'])
# 2. aggregate (6 clips, without hop1) and all 7
for name, clips in [('6 bài (bỏ hop1)', ['quahat','phoi21','phoi42','aldehyd','acid','hop2']), ('bài giảng 5', ['quahat','phoi21','phoi42','aldehyd','acid'])]:
    for m, RR in [('turbo', T), ('pho', P)]:
        N = sum(RR[c]['ref_words'] for c in clips)
        err = sum(RR[c]['sub'] + RR[c]['del'] + RR[c]['ins'] for c in clips)
        ch = 0; ce = 0
        for c in clips:
            ref = E.read_reference(E.DATA / E.CLIPS[c]['ref']); L = len(' '.join(t for _, t in ref)); ch += L; ce += RR[c]['cer'] * L
        te = sum(RR[c]['terms']['term_exact'] for c in clips); tt = sum(RR[c]['terms']['term_total'] for c in clips)
        el = sum(RR[c]['run']['elapsed'] for c in clips); du = sum(RR[c]['run']['duration_ms'] for c in clips) / 1000
        if c == 'phoi42': pass
        S = sum(RR[c]['sub'] for c in clips); D = sum(RR[c]['del'] for c in clips); I = sum(RR[c]['ins'] for c in clips)
        print(f"{name:16} {m:6} N={N} WER {err/N:.2%} CER {ce/ch:.2%} S{S} D{D} I{I} terms {te}/{tt} time {el:.0f}s audio {du:.0f}s RTF {el/du:.3f}")
# 3. stages & format
for m, RR in [('turbo', T), ('pho', P)]:
    for c, r in RR.items():
        st = r['run']['stages']; ss = r['seg_stats']
        print(m, c, 'stages', st, 'dur', r['run']['duration_ms']//1000, 'segs', r['segments'], f"med {ss['median_seg_s']:.1f} max {ss['max_seg_s']:.1f} upper {ss['upper_ratio']:.3f} punct {ss['punct_per_100w']:.1f} digits {ss['digit_tokens']}", 'gaps', r['max_gaps'][:3], 'spk', f"{r['speakers']['accuracy']:.3f} pur {r['speakers']['purity']:.3f} null {r['speakers']['null_words']}")
print('pho flagged hop1', P['hop1']['flagged_segments'])
print('pho del runs'); [print(' ', c, x['t'], x['n'], x['text'][:90]) for c in P for x in P[c]['del_runs']]
