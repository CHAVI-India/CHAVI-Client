"""
A/B test on the MedDeID English synthetic corpus (v3): current JSON-matching
LLM NER vs tagging (full-text echo) strategy, scored against ground-truth
annotated PII spans.

Samples N random development documents (fixed seed), runs both arms
(chunked exactly like production LlmNerClient.find_entities_in_text), and
reports span-level F1 (IoU>=0.5) against the annotated spans, plus a
per-category breakdown and cost.

Usage:
    python extractor/scripts/deid_meddeid_ab.py --n 50 --seed 42
    python extractor/scripts/deid_meddeid_ab.py --n 50 --reps 2 --json-out out.json
"""

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chavi_client.settings')
import django
django.setup()

from extractor.services import llm_ner
from extractor.services.llm_ner import (
    NER_SYSTEM_PROMPT, _normalize_entity_type, _parse_entity_output,
    resolve_spans, chunk_text,
)
from extractor.management.commands.deid_span_ab_test import (
    TAG_SYSTEM_PROMPT, TAG_RE, parse_tagged, MODEL, BASE_URL, API_KEY,
    MAX_TOKENS,
)

# Override: give the tag arm's full echo enough headroom so it isn't
# artificially truncated (the cost difference is still measured).
MAX_TOKENS = 8000

CORPUS = REPO / 'docs/meddeid-english-synthetic-data-v3/data/meddeid-english-synthetic-corpus.jsonl'

# MedDeID category -> our pipeline entity types (for the type-accuracy report)
CAT_TO_TYPES = {
    'Name': {'PERSON'},
    'ID': {'MEDICAL_RECORD_NUMBER', 'PATIENT_ID', 'ID'},
    'Organization': {'ORGANIZATION'},
    'Date': {'DATE_TIME'},
    'Address_Location': {'LOCATION'},
    'Age_Birthdate': {'DATE_TIME', 'AGE'},
    'Contactdetails': {'PHONE_NUMBER', 'EMAIL_ADDRESS'},
    'Profession': set(),  # not a PII type our pipeline redacts
}


def llm_chat(system, user, max_tokens=MAX_TOKENS):
    from openai import OpenAI
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=600)
    t0 = time.monotonic()
    completion = client.chat.completions.create(
        model=MODEL,
        messages=[{'role': 'system', 'content': system},
                  {'role': 'user', 'content': user}],
        temperature=0, max_tokens=max_tokens)
    dt = time.monotonic() - t0
    msg = completion.choices[0].message
    usage = getattr(completion, 'usage', None)
    out_tok = int(getattr(usage, 'completion_tokens', 0) or 0) if usage else 0
    return (msg.content or ''), dt, out_tok


def run_match(text):
    """Production matching arm, chunked like find_entities_in_text."""
    results, seen = [], set()
    dt_tot = tok_tot = 0
    for offset, chunk in chunk_text(text):
        raw, dt, tok = llm_chat(NER_SYSTEM_PROMPT, chunk)
        dt_tot += dt; tok_tot += tok
        try:
            pairs = _parse_entity_output(raw)
        except Exception:
            pairs = []
        typed = []
        for rt, span in pairs:
            et = _normalize_entity_type(rt)
            if et is not None:
                typed.append((et, span))
        for e in resolve_spans(chunk, typed):
            s, en = e['start'] + offset, e['end'] + offset
            key = (e['type'], s, en)
            if key not in seen:
                seen.add(key)
                results.append({'type': e['type'], 'start': s, 'end': en})
    return sorted(results, key=lambda r: (r['start'], r['end'])), dt_tot, tok_tot


def run_tag(text):
    """Tagging arm, chunked the same way."""
    results, seen = [], set()
    dt_tot = tok_tot = 0
    for offset, chunk in chunk_text(text):
        raw, dt, tok = llm_chat(TAG_SYSTEM_PROMPT, chunk)
        dt_tot += dt; tok_tot += tok
        for e in parse_tagged(raw, chunk):
            s, en = e['start'] + offset, e['end'] + offset
            key = (e['type'], s, en)
            if key not in seen:
                seen.add(key)
                results.append({'type': e['type'], 'start': s, 'end': en})
    return sorted(results, key=lambda r: (r['start'], r['end'])), dt_tot, tok_tot


def iou(a, b):
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = max(a[1], b[1]) - min(a[0], b[0])
    return inter / union if union else 0.0


def score_span_f1(gt_spans, pred_spans, iou_thresh=0.5):
    """Greedy IoU matching. gt_spans/pred_spans: list of (start, end)."""
    used = set()
    matched_gt, matched_pred = 0, 0
    # match highest-IoU pairs first
    pairs = []
    for i, g in enumerate(gt_spans):
        for j, p in enumerate(pred_spans):
            v = iou(g, p)
            if v >= iou_thresh:
                pairs.append((v, i, j))
    pairs.sort(reverse=True)
    used_gt, used_pred = set(), set()
    for v, i, j in pairs:
        if i in used_gt or j in used_pred:
            continue
        used_gt.add(i); used_pred.add(j)
    matched_gt = len(used_gt); matched_pred = len(used_pred)
    prec = matched_pred / len(pred_spans) if pred_spans else (1.0 if not gt_spans else 0.0)
    rec = matched_gt / len(gt_spans) if gt_spans else (1.0 if not pred_spans else 0.0)
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {'precision': prec, 'recall': rec, 'f1': f1,
            'matched': matched_gt, 'n_gt': len(gt_spans), 'n_pred': len(pred_spans)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=50)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--reps', type=int, default=1)
    ap.add_argument('--json-out', type=str, default=None)
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    # load + sample
    docs = []
    with open(CORPUS) as f:
        for line in f:
            r = json.loads(line)
            if r.get('annotated'):
                docs.append(r)
    random.seed(args.seed)
    sample = random.sample(docs, args.n)
    print(f"Sampled {len(sample)} docs (seed={args.seed}) from {len(docs)}")

    arms = [('match', run_match), ('tag', run_tag)]
    allres = {d['document_id']: {a: [] for a, _ in arms} for d in sample}
    cat_stats = {a: defaultdict(lambda: {'gt': 0, 'matched': 0, 'pred': 0})
                 for a, _ in arms}

    t_start = time.monotonic()
    for di, doc in enumerate(sample):
        text = doc['text']
        gt = [(s['begin'], s['end'], s['category']) for s in doc['spans']]
        for arm, fn in arms:
            for rep in range(args.reps):
                try:
                    pred, dt, tok = fn(text)
                    sc = score_span_f1(gt, [(p['start'], p['end']) for p in pred])
                    # per-category: which GT categories got a matching pred
                    run = {'f1': sc['f1'], 'precision': sc['precision'],
                           'recall': sc['recall'], 'matched': sc['matched'],
                           'n_gt': sc['n_gt'], 'n_pred': sc['n_pred'],
                           'latency_s': round(dt, 2), 'out_tokens': tok,
                           'pred': [(p['type'], text[p['start']:p['end']])
                                    for p in pred]}
                    # per-category attribution (greedy IoU, per category)
                    used_pred = set()
                    cat_matched = Counter()
                    for (b, e, cat) in gt:
                        best = None
                        for j, p in enumerate(pred):
                            if j in used_pred:
                                continue
                            v = iou((b, e), (p['start'], p['end']))
                            if v >= 0.5 and (best is None or v > best[0]):
                                best = (v, j)
                        if best:
                            used_pred.add(best[1])
                            cat_matched[cat] += 1
                    for cat, cnt in Counter(c for _, _, c in gt).items():
                        cat_stats[arm][cat]['gt'] += cnt
                        cat_stats[arm][cat]['matched'] += cat_matched.get(cat, 0)
                    cat_stats[arm]['__all__']['gt'] += len(gt)
                    cat_stats[arm]['__all__']['pred'] += len(pred)
                except Exception as e:
                    run = {'error': f'{type(e).__name__}: {str(e)[:150]}'}
                allres[doc['document_id']][arm].append(run)
                ok = 'error' not in run
                tag = f"  [{di+1}/{len(sample)}] {doc['document_id'][:22]} {arm}: "
                print(tag + (f"F1={run['f1']:.2f} P={run['precision']:.2f} "
                             f"R={run['recall']:.2f} ({run['matched']}/{run['n_gt']} gt, "
                             f"{run['n_pred']} pred) {run['latency_s']}s {run['out_tokens']}tok"
                             if ok else f"ERROR {run['error']}"), flush=True)
    elapsed = time.monotonic() - t_start

    # ---- report ----
    print("\n" + "=" * 70)
    print(f"MedDeID A/B — {args.n} docs x {args.reps} rep(s) — {elapsed/60:.1f} min")
    print("=" * 70)
    hdr = f"{'arm':<7} {'F1':>5} {'P':>5} {'R':>5} {'matched/gt':>12} {'lat(s)':>7} {'outTok':>7}"
    print(hdr + "-" * (len(hdr) - 1))
    for arm, _ in arms:
        runs = [r for d in allres.values() for r in d[arm] if 'error' not in r]
        if not runs:
            print(f"{arm:<7} {'ERR':>5}"); continue
        f1 = sum(r['f1'] for r in runs) / len(runs)
        prec = sum(r['precision'] for r in runs) / len(runs)
        rec = sum(r['recall'] for r in runs) / len(runs)
        mg = sum(r['matched'] for r in runs); ng = sum(r['n_gt'] for r in runs)
        lat = sum(r['latency_s'] for r in runs) / len(runs)
        tok = sum(r['out_tokens'] for r in runs) / len(runs)
        print(f"{arm:<7} {f1:>5.3f} {prec:>5.3f} {rec:>5.3f} {mg:>6}/{ng:<5} {lat:>7.1f} {tok:>7.0f}")

    print("\nPer-category recall (matched GT / GT):")
    cats = sorted({s['category'] for d in sample for s in d['spans']})
    print(f"{'category':<20} " + "".join(f"{a:>12}" for a, _ in arms))
    for cat in cats:
        row = f"{cat:<20}"
        for arm, _ in arms:
            st = cat_stats[arm][cat]
            r = st['matched'] / st['gt'] if st['gt'] else 0.0
            row += f"{st['matched']:>5}/{st['gt']:<4}({r:.2f})"
        print(row)

    if args.json_out:
        with open(args.json_out, 'w') as fh:
            json.dump({'sample': [d['document_id'] for d in sample],
                       'results': allres,
                       'cat_stats': {a: {k: dict(v) for k, v in c.items()}
                                     for a, c in cat_stats.items()}},
                      fh, indent=2, ensure_ascii=False)
        print(f"\nFull results -> {args.json_out}")


if __name__ == '__main__':
    main()
