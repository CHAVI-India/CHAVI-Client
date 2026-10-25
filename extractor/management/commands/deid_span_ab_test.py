"""
A/B test: current JSON-matching LLM NER  vs  tagging (full-text echo) strategy.

Question
    Does asking the LLM to return the whole text with
    <entity type="...">span</entity> markers (the "tagging" strategy from
    Semin/Dusek/Kasner, "Strategies for Span Labeling with LLMs", arXiv
    2601.16946) beat the current production approach (JSON array of
    {"type","text"} + verbatim-span resolution) for deidentification span
    identification, on our model and our clinical texts?

Arms
    match   PRODUCTION path, unchanged: NER_SYSTEM_PROMPT (JSON array) +
            _parse_entity_output + _normalize_entity_type + resolve_spans
            (exact -> case -> whitespace-collapsed, ordered consumption).
    tag     Same clinical rules, ONLY the output format changes to a full
            verbatim echo with <entity type="...">span</entity> markers.
            Parsed with the paper's approach: running-offset estimate +
            nearest-occurrence fallback.

Fairness
    The clinical rules (verbatim copy, durations-not-dates, no bare
    numbers, no guessing, most-specific-type) are IDENTICAL in both arms.
    Only the output format differs. The resolvers differ by design
    (each arm uses its natural resolver); the report separates detection
    quality from span-resolution success so the format effect is visible.

Test data
    Existing deid test texts from extractor/tests.py (edge cases: duplicate
    names, line-split names, case fallback, MRN/ABHA/PIN, age/duration
    traps) plus the realistic MOCK_DOCUMENT from ab_system_prompt_test.py.
    Golden entities are derived from those tests.

Usage
    python manage.py deid_span_ab_test                 # all texts, 2 reps
    python manage.py deid_span_ab_test --reps 3
    python manage.py deid_span_ab_test --texts t1,t2,mock
    python manage.py deid_span_ab_test --probe         # 1 text, print raw outputs
    python manage.py deid_span_ab_test --json-out ab.json
    python manage.py deid_span_ab_test --verbose

Cost: texts x arms x reps LLM calls. Run unbuffered (python -u) when
redirecting to a log.
"""

import json
import re
import time
from collections import OrderedDict

from django.core.management.base import BaseCommand

from extractor.services import llm_ner
from extractor.services.llm_ner import (
    NER_SYSTEM_PROMPT, ENTITY_TYPES, _normalize_entity_type,
    _parse_entity_output, resolve_spans,
)

# ---------------------------------------------------------------------------
# Model / endpoint (from ClientConfiguration id=1 in the DB)
# ---------------------------------------------------------------------------
MODEL = 'nvidia/Qwen3.8-27B-NVFP4'
BASE_URL = 'http://100.123.143.199:30002/v1'
API_KEY = 'ollama'  # dummy; endpoint is local LAN
MAX_TOKENS = 4000   # reasoning model needs headroom (reasoning + echo)

# ---------------------------------------------------------------------------
# Tagging prompt: IDENTICAL clinical rules to NER_SYSTEM_PROMPT, only the
# output format changes to a full verbatim echo with XML tags.
# ---------------------------------------------------------------------------
_TAG_RULES = NER_SYSTEM_PROMPT.split('Respond with a single JSON array')[0]
TAG_SYSTEM_PROMPT = _TAG_RULES + """OUTPUT FORMAT:
Return a copy of the ENTIRE input text, character for character, with each identified span wrapped in XML tags of the form <entity type="TYPE">SPAN</entity>, where TYPE is one of the types above and SPAN is the verbatim span. The text outside the tags must be an exact copy of the input. If there is no identifiable information, return the input text unchanged with no tags. Do not output any explanations, comments, or markdown - start copying the text immediately."""

TAG_RE = re.compile(r'<entity\s+type="([a-zA-Z_]+)"\s*>(.*?)</entity>', re.DOTALL)


def _nearest_occurrence(source, span, expected_pos):
    """Find the occurrence of `span` in `source` closest to expected_pos.
    Tries exact, then case-insensitive, then whitespace-collapsed."""
    def all_occ(hay, needle):
        occ, i = [], 0
        while True:
            j = hay.find(needle, i)
            if j == -1:
                return occ
            occ.append(j)
            i = j + 1
    for hay, needle, is_collapsed in (
        (source, span, False),
        (source.lower(), span.lower(), False),
    ):
        for j in all_occ(hay, needle):
            yield (abs(j - expected_pos), j, j + len(needle), is_collapsed)
    # whitespace-collapsed fallback via the production index
    idx = llm_ner._SourceIndex(source)
    m = idx.locate(span, 0, case_sensitive=True) or idx.locate(span, 0, case_sensitive=False)
    if m:
        yield (abs(m[0] - expected_pos), m[0], m[1], True)


def parse_tagged(content, source):
    """Paper's tagging parser: running-offset estimate + nearest-occurrence
    fallback. Returns [{'type','start','end'}] sorted by position."""
    content = content or ''
    # Strip a leading code fence if the model added one.
    if content.lstrip().startswith('```'):
        content = content.strip().strip('`').strip()
        if content.lower().startswith('json'):
            content = content[4:].strip()

    # Compute running offset: the source position of each span =
    # (inter-tag text before it) + (lengths of all prior spans), assuming the
    # model echoed the source faithfully. Advance pos by BOTH the inter-tag
    # text and the span length.
    tags = []
    pos = 0
    last_end = 0
    for m in TAG_RE.finditer(content):
        pos += len(content[last_end:m.start()])
        tags.append((m.group(1), m.group(2), pos))
        pos += len(m.group(2))
        last_end = m.end()

    out, seen = [], set()
    for raw_type, span, expected_pos in tags:
        entity_type = _normalize_entity_type(raw_type)
        if entity_type is None:
            continue
        if not span.strip():
            continue
        best = None
        for dist, s, e, _ in _nearest_occurrence(source, span, expected_pos):
            if best is None or dist < best[0]:
                best = (dist, s, e)
        if best is None:
            # last resort: production ordered-consumption locate
            m2 = llm_ner._SourceIndex(source).locate(span, 0, True) \
                or llm_ner._SourceIndex(source).locate(span, 0, False)
            if not m2:
                continue
            s, e = m2
        else:
            s, e = best[1], best[2]
        key = (entity_type, s, e)
        if key in seen:
            continue
        seen.add(key)
        out.append({'type': entity_type, 'start': s, 'end': e})
    return sorted(out, key=lambda x: (x['start'], x['end']))


# ---------------------------------------------------------------------------
# LLM call (shared by both arms)
# ---------------------------------------------------------------------------
def llm_chat(system, user, max_tokens=MAX_TOKENS):
    from openai import OpenAI
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=600)
    t0 = time.monotonic()
    completion = client.chat.completions.create(
        model=MODEL,
        messages=[{'role': 'system', 'content': system},
                  {'role': 'user', 'content': user}],
        temperature=0,
        max_tokens=max_tokens,
    )
    dt = time.monotonic() - t0
    msg = completion.choices[0].message
    usage = getattr(completion, 'usage', None)
    out_tokens = int(getattr(usage, 'completion_tokens', 0) or 0) if usage else 0
    reasoning = int(getattr(usage, 'reasoning_tokens', 0) or 0) if usage else 0
    return (msg.content or ''), dt, out_tokens, reasoning, \
        completion.choices[0].finish_reason


# ---------------------------------------------------------------------------
# Arms
# ---------------------------------------------------------------------------
def run_match(text):
    """Production matching arm. Returns (entities, raw, dt, out_tok, reason,
    finish, n_returned_spans, n_resolved)."""
    raw, dt, out_tok, reason, finish = llm_chat(NER_SYSTEM_PROMPT, text)
    try:
        pairs = _parse_entity_output(raw)
    except Exception:
        pairs = []
    typed = []
    for raw_type, span in pairs:
        et = _normalize_entity_type(raw_type)
        if et is not None:
            typed.append((et, span))
    n_returned = len(typed)
    ents = resolve_spans(text, typed)
    n_resolved = len(ents)
    return ents, raw, dt, out_tok, reason, finish, n_returned, n_resolved


def run_tag(text):
    """Tagging arm. Returns same shape as run_match."""
    raw, dt, out_tok, reason, finish = llm_chat(TAG_SYSTEM_PROMPT, text)
    ents = parse_tagged(raw, text)
    n_returned = len(TAG_RE.findall(raw))
    n_resolved = len(ents)
    return ents, raw, dt, out_tok, reason, finish, n_returned, n_resolved


# ---------------------------------------------------------------------------
# Corpus: existing deid test texts + realistic mock document.
# Golden = list of (presidio_type, verbatim_span). Duplicates listed once;
# scoring counts occurrences.
# ---------------------------------------------------------------------------
def _mock_document():
    from extractor.management.commands.ab_system_prompt_test import MOCK_DOCUMENT
    return MOCK_DOCUMENT


CORPUS = OrderedDict([
    ('t1_dup_name_date', {
        'text': 'Pt Ramesh Kumar seen on 12/03/2024. Ramesh Kumar stable.',
        'golden': [('PERSON', 'Ramesh Kumar'), ('PERSON', 'Ramesh Kumar'),
                   ('DATE_TIME', '12/03/2024')],
    }),
    ('t2_name_date_org', {
        'text': 'Patient Sharma Rao admitted on 01/02/2024 to AIIMS.',
        'golden': [('PERSON', 'Sharma Rao'), ('DATE_TIME', '01/02/2024'),
                   ('ORGANIZATION', 'AIIMS')],
    }),
    ('t3_mrn', {
        'text': 'MR/24/012817 issued.',
        'golden': [('MEDICAL_RECORD_NUMBER', 'MR/24/012817')],
    }),
    ('t5_abha', {
        'text': 'ABHA 91-2345-6789-0123',
        'golden': [('IN_ABHA', '91-2345-6789-0123')],
    }),
    ('t6_pin', {
        'text': 'PIN 560001',
        'golden': [('IN_PINCODE', '560001')],
    }),
    ('t10_age_trap', {
        'text': '45-year-old, nodes 26, lesion 3.2cm, DOB 12/03/1970',
        'golden': [('DATE_TIME', '12/03/1970')],
    }),
    ('t12_triple_dup', {
        'text': 'Dr Rao examined Rao and Rao again.',
        'golden': [('PERSON', 'Rao'), ('PERSON', 'Rao'), ('PERSON', 'Rao')],
    }),
    ('t13_linesplit', {
        'text': 'Admitted: Sharma\nRao, 56 y.',
        'golden': [('PERSON', 'Sharma\nRao')],
    }),
    ('t14_case', {
        'text': 'referred by Dr SHARMA.',
        'golden': [('PERSON', 'SHARMA')],
    }),
    ('mock_realistic', {
        'text': _mock_document(),
        # MOCK_DOCUMENT has no names/phones/MRN; only dates + an age trap.
        'golden': [('DATE_TIME', '28/04/2023'), ('DATE_TIME', '28/04/2023'),
                   ('DATE_TIME', '11/05/2023'), ('DATE_TIME', '11/05/2023'),
                   ('DATE_TIME', '02/06/2023')],
    }),
])


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def _norm_span(s):
    return ' '.join((s or '').split()).lower()


def score_entities_pairs(golden, pred_pairs):
    """golden: [(type, span)], pred_pairs: [(type, span)] (resolved spans)."""
    from collections import Counter
    g = Counter((t, _norm_span(s)) for t, s in golden)
    p = Counter((t, _norm_span(s)) for t, s in pred_pairs)
    tp = sum((g & p).values())
    fp = sum((p - g).values())
    fn = sum((g - p).values())
    prec = tp / (tp + fp) if (tp + fp) else 1.0
    rec = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {'tp': tp, 'fp': fp, 'fn': fn, 'precision': prec,
            'recall': rec, 'f1': f1,
            'false_pos': sorted(set(p - g)), 'false_neg': sorted(set(g - p))}


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------
class Command(BaseCommand):
    help = ('A/B test: current JSON-matching LLM NER vs tagging (full-text '
            'echo) strategy for deid span identification.')

    def add_arguments(self, parser):
        parser.add_argument('--reps', type=int, default=2,
                            help='Repetitions per arm per text (default 2)')
        parser.add_argument('--texts', type=str, default=None,
                            help='Comma-separated corpus keys (default: all)')
        parser.add_argument('--probe', action='store_true',
                            help='Run one text through both arms, print raw outputs')
        parser.add_argument('--verbose', action='store_true',
                            help='Print per-text detail and raw outputs')
        parser.add_argument('--json-out', type=str, default=None,
                            help='Write full results to this JSON file')

    def handle(self, *args, **opts):
        texts = opts['texts'].split(',') if opts['texts'] else list(CORPUS)
        texts = [t.strip() for t in texts if t.strip()]
        missing = [t for t in texts if t not in CORPUS]
        if missing:
            self.stderr.write(self.style.ERROR(
                f"Unknown text(s) {missing}. Available: {list(CORPUS)}"))
            return

        if opts['probe']:
            self._probe(texts[0])
            return

        reps = opts['reps']
        arms = OrderedDict([('match', run_match), ('tag', run_tag)])
        self.stdout.write(self.style.HTTP_INFO(
            f"\nA/B deid span test — model {MODEL}\n"
            f"Texts: {len(texts)} | arms: {list(arms)} | reps: {reps}\n"
            f"Estimated calls: {len(texts) * len(arms) * reps}\n"))

        all_results = {t: {a: [] for a in arms} for t in texts}
        for t in texts:
            text = CORPUS[t]['text']
            for arm, fn in arms.items():
                for rep in range(reps):
                    try:
                        (ents, raw, dt, out_tok, reason, finish,
                         n_ret, n_res) = fn(text)
                        pred_pairs = [(e['type'], text[e['start']:e['end']])
                                      for e in ents]
                        sc = score_entities_pairs(CORPUS[t]['golden'],
                                                  pred_pairs)
                        run = {'f1': sc['f1'], 'precision': sc['precision'],
                               'recall': sc['recall'], 'tp': sc['tp'],
                               'fp': sc['fp'], 'fn': sc['fn'],
                               'false_pos': sc['false_pos'],
                               'false_neg': sc['false_neg'],
                               'n_returned': n_ret, 'n_resolved': n_res,
                               'resolve_rate': (n_res / n_ret) if n_ret else 1.0,
                               'latency_s': round(dt, 2),
                               'out_tokens': out_tok,
                               'reasoning_tokens': reason,
                               'finish': finish, 'raw': raw,
                               'pred': pred_pairs}
                    except Exception as e:
                        run = {'error': f'{type(e).__name__}: {str(e)[:200]}',
                               'raw': None, 'pred': []}
                    all_results[t][arm].append(run)
                    ok = 'error' not in run
                    self.stdout.write(
                        f"  [{t}] {arm} rep{rep}: "
                        + (f"F1={run['f1']:.2f} P={run['precision']:.2f} "
                           f"R={run['recall']:.2f} "
                           f"resolve={run['n_resolved']}/{run['n_returned']} "
                           f"{run['latency_s']}s {run['out_tokens']}tok"
                           if ok else f"ERROR {run['error']}"))

        self._report(all_results, texts, opts)
        if opts['json_out']:
            flat = {t: {a: [{k: v for k, v in r.items() if k != 'raw'}
                           for r in all_results[t][a]] for a in arms}
                    for t in texts}
            with open(opts['json_out'], 'w', encoding='utf-8') as fh:
                json.dump(flat, fh, indent=2, ensure_ascii=False)
            self.stdout.write(self.style.SUCCESS(
                f"\nFull results -> {opts['json_out']}"))

    def _report(self, all_results, texts, opts):
        arms = ['match', 'tag']
        self.stdout.write(self.style.HTTP_INFO(
            "\n" + "=" * 78))
        header = (f"{'text':<18} {'arm':<6} {'F1':>5} {'P':>5} {'R':>5} "
                  f"{'resolv':>7} {'lat(s)':>7} {'outTok':>7}")
        self.stdout.write(self.style.HTTP_INFO(header + "-" * (len(header) - 1)))
        for t in texts:
            for arm in arms:
                runs = [r for r in all_results[t][arm] if 'error' not in r]
                if not runs:
                    self.stdout.write(
                        f"{t:<18} {arm:<6} {'ERR':>5} {'':>5} {'':>5} "
                        f"{'':>7} {'':>7} {'':>7}")
                    continue
                f1 = sum(r['f1'] for r in runs) / len(runs)
                prec = sum(r['precision'] for r in runs) / len(runs)
                rec = sum(r['recall'] for r in runs) / len(runs)
                rr = sum(r['resolve_rate'] for r in runs) / len(runs)
                lat = sum(r['latency_s'] for r in runs) / len(runs)
                tok = sum(r['out_tokens'] for r in runs) / len(runs)
                self.stdout.write(
                    f"{t:<18} {arm:<6} {f1:>5.2f} {prec:>5.2f} {rec:>5.2f} "
                    f"{rr:>7.2f} {lat:>7.1f} {tok:>7.0f}")
        # aggregate
        self.stdout.write(self.style.HTTP_INFO("-" * 78))
        for arm in arms:
            runs = [r for t in texts for r in all_results[t][arm]
                    if 'error' not in r]
            if not runs:
                continue
            f1 = sum(r['f1'] for r in runs) / len(runs)
            prec = sum(r['precision'] for r in runs) / len(runs)
            rec = sum(r['recall'] for r in runs) / len(runs)
            rr = sum(r['resolve_rate'] for r in runs) / len(runs)
            lat = sum(r['latency_s'] for r in runs) / len(runs)
            tok = sum(r['out_tokens'] for r in runs) / len(runs)
            self.stdout.write(self.style.HTTP_INFO(
                f"{'ALL':<18} {arm:<6} {f1:>5.2f} {prec:>5.2f} {rec:>5.2f} "
                f"{rr:>7.2f} {lat:>7.1f} {tok:>7.0f}   (n={len(runs)})"))
        if opts['verbose']:
            self.stdout.write(self.style.HTTP_INFO("\nPer-text detail:\n"))
            for t in texts:
                for arm in arms:
                    for i, r in enumerate(all_results[t][arm]):
                        if 'error' in r:
                            self.stdout.write(f"  [{t}/{arm} rep{i}] ERROR {r['error']}")
                            continue
                        self.stdout.write(
                            f"  [{t}/{arm} rep{i}] F1={r['f1']:.2f} "
                            f"resolve={r['n_resolved']}/{r['n_returned']} "
                            f"FP={r['false_pos']} FN={r['false_neg']}")
            self.stdout.write(self.style.HTTP_INFO("\nRaw outputs (last rep per arm):\n"))
            for t in texts:
                for arm in arms:
                    r = all_results[t][arm][-1]
                    if r.get('raw') is None:
                        continue
                    self.stdout.write(f"\n--- [{t}/{arm}] raw ---\n{r['raw'][:1500]}\n")

    def _probe(self, t):
        text = CORPUS[t]['text']
        self.stdout.write(self.style.HTTP_INFO(
            f"\nPROBE: {t} ({len(text)} chars)\n"
            f"Golden: {CORPUS[t]['golden']}\n"))
        for arm, fn in [('match', run_match), ('tag', run_tag)]:
            ents, raw, dt, out_tok, reason, finish, n_ret, n_res = fn(text)
            self.stdout.write(self.style.HTTP_INFO(
                f"\n=== {arm} === ({dt:.1f}s, {out_tok} out tok, "
                f"{reason} reasoning, finish={finish})"))
            self.stdout.write(f"returned spans: {n_ret}, resolved: {n_res}")
            for e in ents:
                self.stdout.write(f"  {e['type']:<24} {text[e['start']:e['end']]!r}")
            self.stdout.write(f"\n--- raw ---\n{raw[:2000]}\n")
