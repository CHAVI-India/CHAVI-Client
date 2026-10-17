#!/usr/bin/env python3
"""Score the tested deid pipelines on 20 random MedDeID benchmark notes.

Reuses the exact pipeline stages from scripts/pipeline_test.py (gen_candidates
for recall, apply_precision for P1/P2) but runs on arbitrary MedDeID content
(no 14-note catalog, no caching) and scores the resulting redaction spans
against the gold PII spans.

Metrics (span-level, greedy match, min-overlap >= 0.5):
  recall   = gold PII spans we redacted / total gold   (1 - recall = leaks)
  precision= our redactions that hit gold / total ours (1 - precision = over-redaction)
  f1       = harmonic mean
  per-category recall = which MedDeID categories we catch vs miss

Note: Age_Birthdate is intentionally KEPT by this pipeline (age is never
deidentified by product requirement) -> recall ~0 for that category is by
design, not a bug.

Usage:
  venv/bin/python scripts/meddeid_test.py --n 20 --seed 42
  venv/bin/python scripts/meddeid_test.py --n 20 --seed 42 --pipelines R2,R3
"""
import argparse
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chavi_client.settings')

import django
django.setup()

# exact same pipeline stages as the staged test
from pipeline_test import gen_candidates, apply_precision  # noqa: E402

BENCH = os.path.join(
    ROOT, 'docs', 'meddeid-english-synthetic-data-v3', 'data',
    'meddeid-english-synthetic-benchmark.jsonl')

# (label, config, precision) — the pipelines from the staged test
PIPELINES = [
    ('R1 (spaCy+rules)', 'R1', 'P1'),
    ('R2 (Stanford+rules)', 'R2', 'P1'),
    ('R3 shipped (spaCy+Stanford+rules)', 'R3', 'P1'),
    ('R2+gemma (recommendation)', 'R2+gemma', 'P1'),
    ('R2+gemma + nimble precision', 'R2+gemma', 'P2'),
]


def load_notes(n, seed):
    rows = [json.loads(l) for l in open(BENCH)]
    random.Random(seed).shuffle(rows)
    return rows[:n]


def match_ratio(a, b):
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    if inter <= 0:
        return 0.0
    shorter = min(a[1] - a[0], b[1] - b[0])
    return inter / shorter if shorter else 0.0


def score_note(pred, gold):
    """greedy match; gold items are (start, end, category)."""
    used_pred, pairs = set(), []
    for gi, g in enumerate(gold):
        best, best_r = -1, 0.0
        for pi, p in enumerate(pred):
            if pi in used_pred:
                continue
            r = match_ratio(p, g)
            if r >= 0.5 and r > best_r:
                best, best_r = pi, r
        if best >= 0:
            used_pred.add(best)
            pairs.append((best, gi))
    tp = len(pairs)
    recall = tp / len(gold) if gold else 1.0
    precision = tp / len(pred) if pred else 1.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)
    percat = {}
    for s, e, cat in gold:
        percat.setdefault(cat, [0, 0])[1] += 1
    for pi, gi in pairs:
        percat[gold[gi][2]][0] += 1
    return tp, precision, recall, f1, percat, len(pred), len(gold)


def run(label, config, precision, notes, verbose=False, workers=1):
    tp_tot = p_tot = r_tot = 0
    pred_tot = gold_tot = 0
    cat_hit, cat_tot = {}, {}
    per_note = []
    t0 = time.monotonic()
    for note in notes:
        text = note['text']
        gold = [(s['begin'], s['end'], s['category'])
                for s in note['spans'] if s.get('confirmed', True)]
        cands = gen_candidates(text, config, use_cache=False)
        kept = apply_precision(text, cands, precision, workers=workers)
        pred = [(c.start, c.end) for c in kept]
        tp, prec, rec, f1, percat, npred, ngold = score_note(pred, gold)
        tp_tot += tp
        pred_tot += npred
        gold_tot += ngold
        for cat, (h, t) in percat.items():
            cat_hit[cat] = cat_hit.get(cat, 0) + h
            cat_tot[cat] = cat_tot.get(cat, 0) + t
        per_note.append({
            'id': note['document_id'], 'lang': note['metadata'].get('lang'),
            'gold': ngold, 'pred': npred, 'tp': tp,
            'precision': round(prec, 3), 'recall': round(rec, 3),
            'f1': round(f1, 3),
        })
        if verbose:
            print(f'  {note["document_id"]:26s} gold={ngold:2d} pred={npred:2d} '
                  f'tp={tp:2d} P={prec:.2f} R={rec:.2f} F1={f1:.2f}')
    dt = time.monotonic() - t0
    recall = tp_tot / gold_tot if gold_tot else 1.0
    precision = tp_tot / pred_tot if pred_tot else 1.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)
    return {
        'label': label, 'config': config, 'precision': precision,
        'precision_metric': precision, 'recall': recall, 'f1': f1,
        'tp': tp_tot, 'pred': pred_tot, 'gold': gold_tot,
        'over_red': pred_tot - tp_tot, 'leaks': gold_tot - tp_tot,
        'percat': {c: [cat_hit[c], cat_tot[c]] for c in cat_tot},
        'per_note': per_note, 'time': round(dt, 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=20)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--pipelines', default='all',
                    help="comma list of config keys: R1,R2,R3,R2gemma,R2gemmaP2")
    ap.add_argument('--out', default='scripts/results_meddeid.json')
    ap.add_argument('--workers', type=int, default=1)
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    notes = load_notes(args.n, args.seed)
    print(f'MedDeID benchmark: {len(notes)} notes (seed={args.seed})')
    print('selected:', ', '.join(n['document_id'] for n in notes))
    print()

    if args.pipelines == 'all':
        plist = PIPELINES
    else:
        sel = set(args.pipelines.split(','))
        plist = [(l, c, p) for (l, c, p) in PIPELINES
                 if c in sel or c + '_' + p in sel]

    results = []
    for label, config, precision in plist:
        print(f'>>> {label}  [{config} / {precision}] ...')
        res = run(label, config, precision, notes, args.verbose,
                  workers=args.workers)
        results.append(res)
        print(f'    recall={res["recall"]:.3f}  precision={res["precision"]:.3f}'
              f'  f1={res["f1"]:.3f}  (gold={res["gold"]} redacted={res["pred"]} '
              f'leaks={res["leaks"]} over-red={res["over_red"]})  '
              f'{res["time"]}s\n')

    # ---- table ----
    print('\n' + '=' * 74)
    print(f'MedDeID {args.n}-note benchmark  (seed={args.seed})')
    print(f'{("pipeline"):38s} recall  precision  f1   leaks  overred  time')
    print('-' * 74)
    for r in results:
        print(f'{r["label"][:38]:38s} {r["recall"]:.3f}   {r["precision"]:.3f}'
              f'   {r["f1"]:.3f}   {r["leaks"]:4d}   {r["over_red"]:5d}  '
              f'{r["time"]:5.1f}s')
    print('-' * 74)
    print('leaks = gold PII NOT redacted (privacy risk);  '
          'overred = redactions missing gold (clinical over-redaction)')

    # ---- per-category recall on the recommendation ----
    rec = next((r for r in results
                if r['config'] == 'R2+gemma' and r['precision'] == 'P1'),
               results[-1])
    print(f'\nPer-category recall on {rec["label"]}:')
    print(f'  {"category":20s} caught/total   recall')
    for cat, (h, t) in sorted(rec['percat'].items(), key=lambda kv: -kv[1][1]):
        print(f'  {cat:20s} {h:3d}/{t:3d}      {h/t:.3f}')

    json.dump({'n': args.n, 'seed': args.seed,
               'notes': [n['document_id'] for n in notes], 'results': results},
              open(args.out, 'w'), indent=2)
    print(f'\nsaved -> {args.out}')


if __name__ == '__main__':
    main()
