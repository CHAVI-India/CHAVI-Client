#!/usr/bin/env python3
"""Approach A aggregate: shipped pipeline (NER + regex filter) scored with the
same metrics as Approach B, so the two divergent approaches compare cleanly.

Engines:
  presidio  -> spaCy/Stanford NER + Presidio rules + full regex filter (default)
  llm       -> single-pass LLM NER + full regex filter + rules (shipped LLM)

Usage:
  python scripts/approach_a_agg.py            # both engines, all docs
  python scripts/approach_a_agg.py --engine llm
  python scripts/approach_a_agg.py --only cardiology
"""

import argparse
import io
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chavi_client.settings')


def load_catalog():
    src = io.open('scripts/ab_deid_test.py', encoding='utf-8').read()
    ns = {}
    exec(compile(src[src.index('DOC_CLINICAL'):src.index('\ndef ')],
                 'catalog', 'exec'), ns)
    return ns['DOCS'], ns['PII_TOKENS'], ns['CLINICAL_TOKENS'], ns['DATES']


DOCS, PII_TOKENS, CLINICAL_TOKENS, DATES = load_catalog()


def score(source, out):
    sl, out_l = source.lower(), out.lower()
    leaks = [t for t in PII_TOKENS if t.lower() in sl and t.lower() in out_l]
    lost = [t for t in CLINICAL_TOKENS
            if t.lower() in sl and t.lower() not in out_l]
    unshifted = [d for d in DATES if d in source and d in out]
    return leaks, lost, unshifted


def run():
    ap = argparse.ArgumentParser()
    ap.add_argument('--engine', default='both',
                    choices=['presidio', 'llm', 'both'])
    ap.add_argument('--only', default=None)
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    import django
    django.setup()
    from extractor.models import ClientConfiguration
    from extractor.services.llm_ner import LlmNerRecognizer
    from extractor.services.text_deidentification import (
        TextDeidentificationService as S)

    engines = {'presidio', 'llm'} if args.engine == 'both' else {args.engine}
    cfg = ClientConfiguration.objects.get(llm_model_name='gemma4:e2b')
    docs = [d for d in DOCS if args.only is None or args.only in d[0]]

    for engine in sorted(engines):
        agg = {'leaks': 0, 'lost': 0, 'unshifted': 0, 'secs': 0.0}
        ner_rec = None
        if engine == 'llm':
            ner_rec = LlmNerRecognizer(cfg)
        print(f'\n=== Approach A engine={engine}  docs={len(docs)} ===')
        for doc_name, content, _ext in docs:
            random.seed(doc_name)
            shift = random.randint(-45, 45) or 15
            t0 = time.monotonic()
            new_content, _counts, _repl = S._deidentify_text(
                content, shift, None, ner_recognizer=ner_rec)
            secs = time.monotonic() - t0
            leaks, lost, unshifted = score(content, new_content)
            agg['leaks'] += len(leaks)
            agg['lost'] += len(lost)
            agg['unshifted'] += len(unshifted)
            agg['secs'] += secs
            if not args.quiet:
                print(f'  {doc_name[:42]:44s} {secs:5.1f}s leaks={len(leaks)} '
                      f'lost={len(lost)} unshifted={len(unshifted)}')
                for lab, it in (('leaks', leaks), ('lost', lost),
                                ('unshifted', unshifted)):
                    if it:
                        print(f'          {lab}: {it}')
        n = len(docs)
        print(f'  SUMMARY [{engine}]: leaks={agg["leaks"]} lost={agg["lost"]} '
              f'unshifted={agg["unshifted"]} time={agg["secs"]:.0f}s')


if __name__ == '__main__':
    run()
