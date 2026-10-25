#!/usr/bin/env python3
"""Test the DB-configured de-identification pipelines on the MedDeID benchmark.

Runs the PRODUCTION pipeline code (extractor.services.text_deidentification)
for each TextDeidentificationPipelineConfig row in the database, over the
300 human-validated MedDeID English synthetic benchmark documents
(docs/meddeid-english-synthetic-data-v3/), and scores the redacted spans
against the gold PII spans.

No detection logic is added here. Every decision runs through the
production methods — the exact body of
TextDeidentificationService._deidentify_text_for, stopping before the
final text splice (which only rewrites the text and does not change which
spans are redacted):

    analyzer  = S._build_analyzer_for(pipeline)          # Presidio rules +
                                                         # HF NER + Indian IDs
    ad_hoc    = [LlmNerRecognizer(pipeline.system2_model)]  # if system2 set
    results   = analyzer.analyze(text, language='en',
                                 score_threshold=pipeline.min_confidence,
                                 ad_hoc_recognizers=ad_hoc)
    results   = S._apply_precision(text, results, pipeline)
    results   = S._resolve_overlaps(results)

Pipelines tested by default (DB slugs):
  openmed-pii-superclinical-large-434m-v1-no-llm-rules
  openmed-pii-superclinical-large-434m-v1-nvidiaqwen38-27b-nvfp4-rules
  stanford-deidentifier-v2-no-llm-rules
  stanford-deidentifier-v2-nvidiaqwen38-27b-nvfp4-rules

Scoring (same semantics as scripts/meddeid_test.py): span-level greedy
match, min-overlap >= 0.5.
  recall    = gold PII spans redacted / total gold      (1 - recall = leaks)
  precision = our redactions hitting gold / total ours  (1 - precision = over-redaction)

Note: Age_Birthdate recall is partial by design — bare ages are kept by
product requirement; full birthdates are shifted and count as redacted.

Usage:
  venv/bin/python scripts/meddeid_pipeline_db_test.py
  venv/bin/python scripts/meddeid_pipeline_db_test.py --n 5        # smoke
  venv/bin/python scripts/meddeid_pipeline_db_test.py --pipelines all
  venv/bin/python scripts/meddeid_pipeline_db_test.py --list
  venv/bin/python scripts/meddeid_pipeline_db_test.py --no-deid-text
"""
import argparse
import json
import os
import platform
import random
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chavi_client.settings')

import django
django.setup()

from extractor.models import TextDeidentificationPipelineConfig  # noqa: E402
from extractor.services.llm_ner import LlmNerRecognizer  # noqa: E402
from extractor.services.text_deidentification import (  # noqa: E402
    TextDeidentificationService as S)

DATA_DIR = os.path.join(ROOT, 'docs', 'meddeid-english-synthetic-data-v3')
BENCH = os.path.join(
    DATA_DIR, 'data', 'meddeid-english-synthetic-benchmark.jsonl')

DEFAULT_SLUGS = [
    'openmed-pii-superclinical-large-434m-v1-no-llm-rules',
    'openmed-pii-superclinical-large-434m-v1-nvidiaqwen38-27b-nvfp4-rules',
    'stanford-deidentifier-v2-no-llm-rules',
    'stanford-deidentifier-v2-nvidiaqwen38-27b-nvfp4-rules',
]

# Transient LLM/network failures must not kill a long run: retry the
# document, then record the error and continue.
MAX_DOC_ATTEMPTS = 3
RETRY_WAIT_S = 5


# ----------------------------------------------------------------------
# scoring (identical semantics to scripts/meddeid_test.py)
# ----------------------------------------------------------------------

def match_ratio(a, b):
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    if inter <= 0:
        return 0.0
    shorter = min(a[1] - a[0], b[1] - b[0])
    return inter / shorter if shorter else 0.0


def score_note(pred, gold):
    """Greedy match; gold items are (start, end, category)."""
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


# ----------------------------------------------------------------------
# loading
# ----------------------------------------------------------------------

def load_pipelines(spec):
    if spec == 'all':
        return list(TextDeidentificationPipelineConfig.objects.all())
    out = []
    for slug in spec.split(','):
        slug = slug.strip()
        if not slug:
            continue
        p = (TextDeidentificationPipelineConfig.objects
             .filter(slug=slug).first()
             or TextDeidentificationPipelineConfig.objects
             .filter(name=slug).first())
        if p is None:
            raise SystemExit(f'pipeline not found in DB: {slug!r}')
        out.append(p)
    return out


def load_notes(n, seed):
    rows = [json.loads(l) for l in open(BENCH)]
    if n and n < len(rows):
        random.Random(seed).shuffle(rows)
        rows = rows[:n]
    return rows


# ----------------------------------------------------------------------
# production pipeline run
# ----------------------------------------------------------------------

def run_doc_production(content, pipeline, analyzer, ad_hoc):
    """Exact body of S._deidentify_text_for minus the final text splice.

    Returns the kept (post-precision, post-overlap-resolution) results —
    i.e. exactly the spans the production pipeline would redact.
    """
    results = analyzer.analyze(
        text=content, language='en',
        score_threshold=pipeline.min_confidence,
        ad_hoc_recognizers=ad_hoc)
    results = S._apply_precision(content, results, pipeline)
    results = S._resolve_overlaps(results)
    return results


def pipeline_info(pipeline):
    s2 = pipeline.system2_model
    return {
        'slug': pipeline.slug,
        'name': pipeline.name,
        'ner_engine': pipeline.ner_engine,
        'hf_model_id': pipeline.hf_model_id,
        'hf_threshold': pipeline.hf_threshold,
        'hf_label_map': pipeline.hf_label_map,
        'min_confidence': pipeline.min_confidence,
        'system2_model': s2.llm_model_name if s2 else None,
        'system2_base_url': s2.model_base_url if s2 else None,
        'system_1_model_integration': pipeline.system_1_model_integration,
        'rules': pipeline.rules,
    }


def run_pipeline(pipeline, notes, shift, save_text, verbose):
    # production wiring: analyzer per pipeline config, LLM as ad-hoc
    # recognizer when a system-2 model is configured
    analyzer = S._build_analyzer_for(pipeline)
    ad_hoc = []
    if pipeline.system2_model_id:
        ad_hoc = [LlmNerRecognizer(pipeline.system2_model)]

    tp_tot = pred_tot = gold_tot = 0
    cat_hit, cat_tot = {}, {}
    per_note, errors, deid_texts = [], [], {}
    t0 = time.monotonic()
    for i, note in enumerate(notes, 1):
        text = note['text']
        gold = [(s['begin'], s['end'], s['category'])
                for s in note['spans'] if s.get('confirmed', True)]
        t_doc = time.monotonic()
        results, last_err = None, None
        for attempt in range(1, MAX_DOC_ATTEMPTS + 1):
            try:
                results = run_doc_production(
                    text, pipeline, analyzer, ad_hoc)
                last_err = None
                break
            except Exception as e:  # noqa: BLE001 - record and continue
                last_err = e
                if verbose:
                    print(f'    [{note["document_id"]} attempt {attempt}] '
                          f'{type(e).__name__}: {e}')
                if attempt < MAX_DOC_ATTEMPTS:
                    time.sleep(RETRY_WAIT_S)
        if last_err is not None:
            errors.append({'document_id': note['document_id'],
                           'error': f'{type(last_err).__name__}: {last_err}'})
            if not verbose:
                print(f'  !! {note["document_id"]}: {last_err}')
            continue

        pred = [(r.start, r.end) for r in results]
        deid_text = S._apply_replacements(text, results, shift, {}, [])
        tp, prec, rec, f1, percat, npred, ngold = score_note(pred, gold)
        tp_tot += tp
        pred_tot += npred
        gold_tot += ngold
        for cat, (h, t) in percat.items():
            cat_hit[cat] = cat_hit.get(cat, 0) + h
            cat_tot[cat] = cat_tot.get(cat, 0) + t
        per_note.append({
            'id': note['document_id'],
            'lang': note['metadata'].get('lang'),
            'gold': ngold, 'pred': npred, 'tp': tp,
            'precision': round(prec, 3), 'recall': round(rec, 3),
            'f1': round(f1, 3), 'time_s': round(time.monotonic() - t_doc, 1),
        })
        if save_text:
            deid_texts[note['document_id']] = deid_text
        if verbose:
            print(f'  {i:3d}/{len(notes)} {note["document_id"]:26s} '
                  f'gold={ngold:2d} pred={npred:2d} tp={tp:2d} '
                  f'P={prec:.2f} R={rec:.2f} F1={f1:.2f} '
                  f'{time.monotonic() - t_doc:5.1f}s')

    dt = time.monotonic() - t0
    recall = tp_tot / gold_tot if gold_tot else 1.0
    precision = tp_tot / pred_tot if pred_tot else 1.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)
    return {
        **pipeline_info(pipeline),
        'metrics': {
            'recall': round(recall, 4), 'precision': round(precision, 4),
            'f1': round(f1, 4),
            'tp': tp_tot, 'pred': pred_tot, 'gold': gold_tot,
            'leaks': gold_tot - tp_tot, 'over_red': pred_tot - tp_tot,
            'per_category': {c: {'caught': cat_hit[c], 'total': cat_tot[c],
                                 'recall': round(cat_hit[c] / cat_tot[c], 4)}
                             for c in sorted(cat_tot)},
            'time_s': round(dt, 1),
        },
        'errors': errors,
        'per_note': per_note,
        **({'deidentified': deid_texts} if save_text else {}),
    }


# ----------------------------------------------------------------------
# main
# ----------------------------------------------------------------------

def main():
    # live log updates even when stdout is redirected to a file
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--pipelines', default=','.join(DEFAULT_SLUGS),
                    help='comma list of DB slugs/names, or "all"')
    ap.add_argument('--n', type=int, default=0,
                    help='number of notes to test (0 = all 300)')
    ap.add_argument('--seed', type=int, default=42,
                    help='seed for the random subset (only used with --n)')
    ap.add_argument('--shift', type=int, default=90,
                    help='fixed date shift in days for the stored '
                         'deidentified text (production uses a random '
                         'per-document shift; does not affect scoring)')
    ap.add_argument('--out', default=None,
                    help='output JSON path (default: '
                         '<data dir>/pipeline-test-<n>.json)')
    ap.add_argument('--no-deid-text', action='store_true',
                    help='do not store the deidentified text per note')
    ap.add_argument('--list', action='store_true',
                    help='list pipelines in the DB and exit')
    ap.add_argument('--verbose', action='store_true')
    args = ap.parse_args()

    if args.list:
        for p in TextDeidentificationPipelineConfig.objects.all():
            s2 = p.system2_model
            print(f'{p.slug:60s} {p.ner_engine:5s} '
                  f'{p.hf_model_id or "-":45s} '
                  f'{s2.llm_model_name if s2 else "no-LLM"}')
        return

    pipelines = load_pipelines(args.pipelines)
    notes = load_notes(args.n, args.seed)
    out_path = args.out or os.path.join(
        DATA_DIR, f'pipeline-test-{len(notes)}.json')

    print(f'MedDeID benchmark: {len(notes)} notes '
          f'({args.n or "all"}, seed={args.seed})')
    print(f'Pipelines ({len(pipelines)}):')
    for p in pipelines:
        s2 = p.system2_model
        print(f'  - {p.name}  [{p.hf_model_id or p.ner_engine} | '
              f'{s2.llm_model_name if s2 else "no-LLM"} | '
              f'min_confidence={p.min_confidence}]')
    print()

    base, ext = os.path.splitext(out_path)
    if not ext:
        ext = '.json'

    results = []
    for p in pipelines:
        print(f'>>> {p.name}  [{p.slug}] ...')
        res = run_pipeline(p, notes, args.shift,
                           save_text=not args.no_deid_text,
                           verbose=args.verbose)
        results.append(res)
        # incremental safety net: persist this pipeline's result as soon as
        # it completes, so a crash in a later (e.g. LLM) pipeline does not
        # lose the finished work. Re-run a single pipeline with
        # --pipelines <slug> if needed.
        per_path = f'{base}-{p.slug}{ext}'
        with open(per_path, 'w') as f:
            json.dump(res, f, indent=2)
        print(f'    saved -> {per_path}')
        m = res['metrics']
        print(f'    recall={m["recall"]:.3f}  precision={m["precision"]:.3f}'
              f'  f1={m["f1"]:.3f}  (gold={m["gold"]} redacted={m["pred"]} '
              f'leaks={m["leaks"]} over-red={m["over_red"]})  '
              f'{m["time_s"]}s'
              + (f'  ERRORS={len(res["errors"])}' if res['errors'] else '')
              + '\n')

    # ---- summary table ----
    print('=' * 78)
    print(f'MedDeID benchmark  ({len(notes)} notes, '
          f'{sum(r["metrics"]["gold"] for r in results) // max(len(results), 1)} '
          f'gold spans/note)')
    print(f'{("pipeline"):52s} recall  precision  f1   leaks  overred  time')
    print('-' * 78)
    for r in results:
        m = r['metrics']
        print(f'{r["name"][:52]:52s} {m["recall"]:.3f}   '
              f'{m["precision"]:.3f}   {m["f1"]:.3f}   '
              f'{m["leaks"]:4d}   {m["over_red"]:5d}  {m["time_s"]:6.1f}s')
    print('-' * 78)
    print('leaks = gold PII NOT redacted (privacy risk);  '
          'overred = redactions missing gold (over-redaction)')

    # ---- per-category recall per pipeline ----
    for r in results:
        print(f'\nPer-category recall — {r["name"]}:')
        print(f'  {"category":20s} caught/total   recall')
        for cat, v in sorted(r['metrics']['per_category'].items(),
                             key=lambda kv: -kv[1]['total']):
            print(f'  {cat:20s} {v["caught"]:3d}/{v["total"]:3d}      '
                  f'{v["recall"]:.3f}')

    payload = {
        'test': 'meddeid-pipeline-db-test',
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'dataset': {
            'path': os.path.relpath(BENCH, ROOT),
            'documents': len(notes),
            'seed': args.seed if args.n else None,
            'note': 'all 300 benchmark documents' if not args.n
                    else f'{args.n} random documents (seed={args.seed})',
        },
        'date_shift_days': args.shift,
        'date_shift_note': 'fixed for reproducibility of the stored '
                           'deidentified text; production uses a random '
                           'per-document shift. Does not affect scoring.',
        'environment': {
            'python': platform.python_version(),
            'transformers': _pkg('transformers'),
            'torch': _pkg('torch'),
            'presidio_analyzer': _pkg('presidio_analyzer'),
        },
        'results': results,
    }
    with open(out_path, 'w') as f:
        json.dump(payload, f, indent=2)
    print(f'\nsaved -> {out_path}')


def _pkg(name):
    try:
        import importlib.metadata as md
        return md.version(name)
    except Exception:
        return None


if __name__ == '__main__':
    main()
