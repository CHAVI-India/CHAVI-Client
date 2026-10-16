#!/usr/bin/env python3
"""Staged de-identification pipeline comparison harness.

See docs/superpowers/plans/2026-10-17-deid-pipeline-test.md.

Recall config = base traditional NER (R1/R2/R3) + optional LLM additions
(+gemma, +openmed). Precision = P1 (production clinical filter) or P2
(nimble System-1 judge on non-date spans). Dates are always T0 (code).

  venv/bin/python scripts/pipeline_test.py --config R3 --precision P1
  venv/bin/python scripts/pipeline_test.py --config R3+gemma --precision P1
  venv/bin/python scripts/pipeline_test.py --config R3+openmed --precision P2
"""
import argparse, json, os, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chavi_client.settings')
import django
django.setup()

from django.conf import settings
from extractor.services.text_deidentification import (
    TextDeidentificationService as S)
from deid_ground_truth import (DOCS, score, propagate_spans)
from presidio_analyzer import RecognizerResult

# --- nimble System-1 judge (self-contained; test-only concern) ---
SYSTEMONE_URL = 'http://localhost:11434/v1/systemone'
SYSTEMONE_MODEL = 'nimble'
PHI_THRESHOLD = 0.5
IS_PHI_QUESTION = (
    'Is the span marked «...» personally identifiable or private medical '
    'information that should be de-identified from this clinical note? Count '
    'it as PHI only if it is a person\'s name, a location/address, an '
    'organisation, a phone or ID number, or a calendar date. Do NOT count it '
    'if it is a diagnosis or disease ("DM", "CCF", "Hypertension"), a '
    'medication or drug ("Tab Amlodipine 5", "Tramadol", "Ceftriaxone"), a '
    'dose, a lab value, a vital sign ("SpO2", "BP", "HR"), a clinical role '
    '("Attendant", "Doctor", "Nurse"), a duration/interval, or an age. If it '
    'is a medical term, answer NO.')


def _so_post(state, questions):
    payload = json.dumps({'model': SYSTEMONE_MODEL, 'state': state,
                          'questions': questions}).encode('utf-8')
    req = urllib.request.Request(
        SYSTEMONE_URL, data=payload,
        headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode('utf-8')).get('answers', {})


def _so_noul(answers, name):
    return float(answers.get(name, {}).get('noul', 0.0))


def _build_context(text, start, end, window=90):
    surf = text[start:end]
    ws, we = max(0, start - window), min(len(text), end + window)
    excerpt = text[ws:we]
    rel = start - ws
    return excerpt[:rel] + '«' + surf + '»' + excerpt[rel + len(surf):]


# --- recognizers (lazy singletons) ---
_LLM_REC = _OM_REC = None


def _ensure_gemma_cfg():
    from extractor.models import ClientConfiguration
    cfg = ClientConfiguration.objects.filter(
        llm_model_name='gemma4:e2b').first()
    if cfg:
        cfg.enable_text_deid = True
        cfg.deid_local_certified = True
        cfg.save()
        return cfg
    return ClientConfiguration.objects.create(
        llm_model_name='gemma4:e2b', model_provider='Local (Ollama)',
        model_api_key='ollama', model_base_url='http://localhost:11434',
        request_timeout=300, context_size=131072, enable_text_deid=True,
        deid_local_certified=True, is_default_deid=False)


def get_llm_rec():
    global _LLM_REC
    if _LLM_REC is None:
        from extractor.services.llm_ner import LlmNerRecognizer
        _LLM_REC = LlmNerRecognizer(_ensure_gemma_cfg())
    return _LLM_REC


def get_openmed_rec():
    global _OM_REC
    if _OM_REC is None:
        from extractor.services.openmed_ner import OpenMedNerRecognizer
        _OM_REC = OpenMedNerRecognizer()
    return _OM_REC


# --- recall: candidate generation (cached to disk per config+note) ---
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.cache')


def parse_config(config):
    parts = config.split('+')
    base, adds = parts[0], set(parts[1:])
    if base not in ('R1', 'R2', 'R3'):
        raise ValueError('bad recall base: ' + base)
    if not adds <= {'gemma', 'openmed'}:
        raise ValueError('bad recall additions: ' + ','.join(adds))
    return base, adds


def _cache_path(config):
    return os.path.join(
        CACHE_DIR, 'cands_' + config.replace('+', '_') + '.json')


class _Cand:
    def __init__(self, t, a, b, sc):
        self.entity_type, self.start, self.end, self.score = t, a, b, sc


def name_of(content):
    for name, c, _ in DOCS:
        if c == content:
            return name
    raise ValueError('content not in catalog')


def gen_candidates(content, config, use_cache):
    base, adds = parse_config(config)
    path = _cache_path(config)
    if use_cache and os.path.exists(path):
        by_name = {r['name']: r['cands']
                   for r in json.load(open(path))}
        nm = name_of(content)
        if nm in by_name:
            return [_Cand(*c) for c in by_name[nm]]
    thr = getattr(settings, 'EXTRACTOR_DEID_SCORE_THRESHOLD', 0.35)
    analyzer, _ = S._build_analyzer(
        include_hf_ner=(base != 'R1'), slim_ner=(base == 'R2'))
    ad_hoc = []
    if 'gemma' in adds:
        ad_hoc.append(get_llm_rec())
    if 'openmed' in adds:
        ad_hoc.append(get_openmed_rec())
    raw = analyzer.analyze(text=content, language='en', score_threshold=thr,
                           ad_hoc_recognizers=ad_hoc or None)
    seen, cands = set(), []
    for r in raw:
        k = (r.entity_type, r.start, r.end)
        if k in seen:
            continue
        seen.add(k)
        cands.append([r.entity_type, r.start, r.end, r.score])
    if use_cache:
        os.makedirs(CACHE_DIR, exist_ok=True)
        _upsert_cache(path, name_of(content), cands)
    return [_Cand(*c) for c in cands]


def _upsert_cache(path, name, cands):
    rows = json.load(open(path)) if os.path.exists(path) else []
    rows = [r for r in rows if r['name'] != name]
    rows.append({'name': name, 'cands': cands})
    json.dump(rows, open(path, 'w'))


# --- precision + application ---
def apply_precision(content, cands, precision, verbose=False, workers=1):
    if precision == 'P1':
        return S._filter_results(content, cands)  # monolith == production
    # P2: mechanical + dates (same as production) + nimble (replaces clinical)
    cands = S._filter_mechanical(content, cands)
    kept, non_date = [], []
    for r in cands:
        if r.entity_type in ('DATE_TIME', 'DATE'):
            if S._filter_dates(content, [r]):
                kept.append(r)
        else:
            non_date.append(r)

    def judge(r):
        state = {'excerpt': _build_context(content, r.start, r.end, 90)}
        ans = _so_post(state, {'is_phi': {
            'type': 'noul', 'instructions': IS_PHI_QUESTION}})
        return r, _so_noul(ans, 'is_phi')

    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            judged = list(ex.map(judge, non_date))
    else:
        judged = [judge(r) for r in non_date]
    for r, p in judged:
        if verbose:
            print(f'    [P2 {r.entity_type:16s} '
                  f'{content[r.start:r.end]!r:26s} p={p:.2f} '
                  f'-> {"DEID" if p >= PHI_THRESHOLD else "keep"}]')
        if p >= PHI_THRESHOLD:
            kept.append(r)
    return kept


def run_doc(name, content, config, precision, shift, use_cache,
            verbose=False, workers=1):
    cands = gen_candidates(content, config, use_cache)
    kept = apply_precision(content, cands, precision, verbose, workers)
    kept = S._resolve_overlaps(kept)
    spans = [{'type': r.entity_type, 'start': r.start, 'end': r.end,
              'score': r.score} for r in kept]
    spans = propagate_spans(content, spans)
    results = [RecognizerResult(entity_type=s['type'], start=s['start'],
                                end=s['end'], score=s.get('score', 0.9))
               for s in spans]
    results = S._resolve_overlaps(results)
    return S._apply_replacements(content, results, shift, {}, [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True,
                    help='R1|R2|R3, optionally +gemma / +openmed')
    ap.add_argument('--precision', required=True, choices=['P1', 'P2'])
    ap.add_argument('--only', default=None,
                    help='substring filter on note name')
    ap.add_argument('--out', default=None, help='write JSON result file')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--no-cache', action='store_true')
    ap.add_argument('--workers', type=int, default=1,
                    help='parallel nimble-judge workers (P2 only)')
    args = ap.parse_args()

    shift = 15  # fixed; scoring only checks whether a date string changed
    rows, agg = [], [0, 0, 0]
    t_all = time.monotonic()
    for name, content, ext in DOCS:
        if args.only and args.only not in name:
            continue
        t0 = time.monotonic()
        out = run_doc(name, content, args.config, args.precision, shift,
                      not args.no_cache, args.verbose, args.workers)
        dt = time.monotonic() - t0
        leaks, lost, unshifted = score(content, out)
        agg[0] += len(leaks)
        agg[1] += len(lost)
        agg[2] += len(unshifted)
        rows.append({'doc': name, 'leaks': leaks, 'lost': lost,
                     'unshifted': unshifted, 'time': round(dt, 1)})
        print(f'{name[:42]:44s} leaks={len(leaks):2d} lost={len(lost):2d} '
              f'unshifted={len(unshifted):2d} {dt:6.1f}s')
    print(f'== {args.config} {args.precision}: leaks={agg[0]} lost={agg[1]} '
          f'unshifted={agg[2]} total={time.monotonic() - t_all:.0f}s ==')
    if args.out:
        json.dump({'config': args.config, 'precision': args.precision,
                   'agg': agg, 'rows': rows}, open(args.out, 'w'), indent=2)


if __name__ == '__main__':
    main()
