#!/usr/bin/env python3
"""Approach B: multi-pass LLM span-identification + code-level redaction.

Divergent from the shipped Approach A (single NER pass + regex filter +
deterministic shift). Here:

  * The LLM IDENTIFIES PII spans on the ORIGINAL text only. It never sees a
    deidentified document, never rewrites the note, and never shifts dates.
  * Independent passes are unioned (the model is non-deterministic even at
    temperature=0, so each pass is a fresh sample -> recall boost).
  * Pass 2 checks for spans "extra" to pass 1; if any, pass 3 finalizes.
  * Redaction + date shifting are done in CODE, reusing the production
    _filter_results / _resolve_overlaps / _apply_replacements (date shift is
    deterministic date arithmetic, not LLM arithmetic).
  * A minimal regex safety net covers the structured IDs small models miss.

Usage:
  python scripts/deid_approach_b.py                 # gemma4:e2b, full multi-pass
  python scripts/deid_approach_b.py --passes 1      # single-pass baseline
  python scripts/deid_approach_b.py --no-safenet
  python scripts/deid_approach_b.py --only cardiology
"""

import argparse
import io
import json
import os
import random
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Reuse the document + token catalog from the Approach-A A/B script.
# ---------------------------------------------------------------------------

def load_catalog():
    src = io.open('scripts/ab_deid_test.py', encoding='utf-8').read()
    ns = {}
    exec(compile(src[src.index('DOC_CLINICAL'):src.index('\ndef ')],
                 'catalog', 'exec'), ns)
    return ns['DOCS'], ns['PII_TOKENS'], ns['CLINICAL_TOKENS'], ns['DATES']


DOCS, PII_TOKENS, CLINICAL_TOKENS, DATES = load_catalog()


# ---------------------------------------------------------------------------
# Minimal safety net: ONLY the structured IDs small models reliably miss.
# (The point of the experiment is that clinical content is protected by the
#  LLM's judgment, not by a bag of protection regexes.)
# ---------------------------------------------------------------------------

SAFENET = [
    ('IN_AADHAAR', re.compile(r'\b\d{4}\s\d{4}\s\d{4}\b|\b\d{12}\b')),
    ('MEDICAL_RECORD_NUMBER', re.compile(r'\b[A-Z]{2,3}/\d{2}/\d{4,}\b')),
    ('IN_MOBILE_NUMBER', re.compile(r'\+91\s?\d{5}\s?\d{5}\b')),
]


def safenet_spans(text):
    out = []
    for etype, pat in SAFENET:
        for m in pat.finditer(text):
            out.append({'type': etype, 'start': m.start(), 'end': m.end(),
                        'score': 0.95})
    return out


# Entity types that repeat verbatim in a note and should be redacted at
# every occurrence. Dates are excluded: a short date surface (e.g. '2/2') is
# a substring of other dates ('12/2/24'), so blind propagation is unsafe.
PROPAGATE_TYPES = {
    'PERSON', 'LOCATION', 'ORGANIZATION', 'MEDICAL_RECORD_NUMBER',
    'IN_AADHAAR', 'IN_MOBILE_NUMBER', 'IN_PINCODE', 'IN_ABHA', 'IN_UPI',
    'IN_DRIVING_LICENSE', 'PATIENT_ID',
}


def propagate_spans(text, span_list):
    """Extend each identified entity to ALL identical occurrences in text.

    Small models report a repeated name once; de-identification requires
    every occurrence to be redacted. This is deterministic (findall), so the
    recall gap is closed in code, not by asking the LLM to re-list the name.
    `finditer` owns all occurrence discovery (it always re-finds the original
    position, since text[a:b] == surface); input de-duplication uses a
    separate set so single-occurrence entities are not swallowed.
    """
    dedup, input_seen = [], set()
    for s in span_list:
        key = (s['type'], s['start'], s['end'])
        if key in input_seen:
            continue
        input_seen.add(key)
        dedup.append(s)
    out, out_seen = [], set()
    for s in dedup:
        t, a, b = s['type'], s['start'], s['end']
        surface = text[a:b]
        if t not in PROPAGATE_TYPES or not surface.strip():
            key = (t, a, b)
            if key not in out_seen:
                out_seen.add(key)
                out.append(s)
            continue
        for m in re.finditer(re.escape(surface), text):
            key = (t, m.start(), m.end())
            if key in out_seen:
                continue
            out_seen.add(key)
            out.append({'type': t, 'start': m.start(), 'end': m.end(),
                       'score': s.get('score', 0.9)})
    return out


# ---------------------------------------------------------------------------
# Scoring (identical logic to the Approach-A A/B)
# ---------------------------------------------------------------------------

def score(source, out):
    sl, out_l = source.lower(), out.lower()
    leaks = [t for t in PII_TOKENS if t.lower() in sl and t.lower() in out_l]
    lost = [t for t in CLINICAL_TOKENS
            if t.lower() in sl and t.lower() not in out_l]
    unshifted = [d for d in DATES if d in source and d in out]
    return leaks, lost, unshifted


# ---------------------------------------------------------------------------
# Approach D: LLM-as-reviewer. spaCy+rules does the base deid; the LLM sees
# the deidentified note + the identified list and reports (a) PII still
# visible (missed) and (b) clinical content wrongly redacted (restore).
# The LLM is told to IGNORE ALL DATES. Code applies the corrections via
# verbatim lookup, so the LLM never rewrites (or re-leaks) the text.
# ---------------------------------------------------------------------------

REVIEW_SYSTEM_PROMPT = """You are reviewing a de-identified clinical note for
quality. You are given:
1. The DE-IDENTIFIED note (identifiers replaced by tags).
2. The IDENTIFIED LIST: each tag, the exact original text it replaced, and
   its type.

Report ONLY two kinds of problem:
A. MISSED: personally identifiable information still visible in the
   de-identified note — a person's name, a location/address, an
   organisation, a phone number, or an ID/record number. Report the exact
   verbatim text as it appears in the de-identified note, and its type.
B. OVER-REDACTED: clinical content that was incorrectly redacted —
   medications with doses, lab values and units, vitals, tumour sizes,
   staging, grading, treatment counts, clinical times. Report the exact
   original text (from the IDENTIFIED LIST) that should be restored.

STRICT RULES:
- IGNORE ALL DATES. Do not report, question, or suggest any change to any
  date, year, month, day, duration, interval, or time — even if it looks
  odd or inconsistent. Dates are handled by a separate process.
- Do not report ages.
- Report ONLY real text, never tags. A <TAG> is already redacted — it is
  NOT a "missed" item. Do not copy or repeat any tag in your answer.
- Only report items actually present in the provided texts. Never guess.
- Copy text VERBATIM (exact characters, case, spacing).
- Keep the answer short.

Respond with a single JSON object and nothing else:
{"missed": [{"type": "person|location|organization|phone|id", "text": "..."}],
 "restored": ["...", "..."]}
Use empty arrays when there is no problem. No prose, no markdown."""

REVIEW_TYPE_MAP = {
    'person': 'PERSON', 'name': 'PERSON', 'patient': 'PERSON',
    'location': 'LOCATION', 'address': 'LOCATION', 'place': 'LOCATION',
    'organization': 'ORGANIZATION', 'organisation': 'ORGANIZATION',
    'org': 'ORGANIZATION', 'hospital': 'ORGANIZATION',
    'phone': 'PHONE_NUMBER', 'phone_number': 'PHONE_NUMBER',
    'id': 'MEDICAL_RECORD_NUMBER', 'mrn': 'MEDICAL_RECORD_NUMBER',
    'id_number': 'MEDICAL_RECORD_NUMBER', 'record_number': 'MEDICAL_RECORD_NUMBER',
}


def _parse_review_output(content):
    """Lenient parse of the reviewer JSON -> (missed, restored)."""
    import json
    text = (content or '').strip()
    if text.startswith('```'):
        text = text.strip('`').strip()
        if text.lower().startswith('json'):
            text = text[4:].strip()
    candidates = [text]
    s, e = text.find('{'), text.rfind('}')
    if s != -1 and e > s:
        candidates.append(text[s:e + 1])
    for cand in candidates:
        try:
            data = json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        missed, restored = [], []
        for item in data.get('missed', []):
            if isinstance(item, dict):
                missed.append((str(item.get('type', '')),
                               str(item.get('text', ''))))
            elif isinstance(item, str):
                missed.append(('', item))
        for item in data.get('restored', []):
            if isinstance(item, str):
                restored.append(item)
            elif isinstance(item, dict):
                restored.append(str(item.get('text', '')))
        return missed, restored
    raise ValueError(f'unparseable reviewer output: {content[:200]!r}')


def _norm(t):
    return ' '.join((t or '').split()).lower()


# Shared surface filter for date-like clinical content (never a real date).
# Used by both the minimal filter and the union engine.
DATE_SURFACE_RE = re.compile(
    r'^\d{1,3}%?$'
    r'|^(?:age\b:?\s*)?\d{1,3}\s*[-\s]?(years?\s+old|yrs?\s+old|years?|yrs?|y/o|y\.o\.|-?year-?old)\.?$'
    r'|^age\b:?\s*\d{1,3}\s*(years?|yrs?)?\.?$'
    r'|^\d{1,3}\s*(years?|yrs?|y)?\s*/\s*[MF]\b\.?$'
    r'|^[MF]\s*/\s*\d{1,3}\s*(years?|yrs?|y)?\b\.?$'
    r'|^\d{1,3}(?:\s*-\s*\d{1,3})?\s+(years?|months?|mnths?|mths?|mos?|weeks?|wks?|days?|hrs?|hours?|hourly|mins?|minutes?)\b\.?$'
    r'|^\d{1,3}\s*/\s*min\b\.?$'
    r'|^\d{1,2}:\d{2}$'
    r'|^[a-z][a-z]+\s+\d+(?:\.\d+)?\s*(g|mg|gm|ml)?\b\.?$', re.I)


def _is_date_surface(surface):
    return bool(DATE_SURFACE_RE.match(surface))


def _word_boundary_ok(text, start, end):
    raw = text[start:end]
    b_start = start + (len(raw) - len(raw.lstrip()))
    b_end = end - (len(raw) - len(raw.rstrip()))
    if b_start > 0 and text[b_start - 1].isalnum():
        return False
    if b_end < len(text) and text[b_end].isalnum():
        return False
    return True


def _principled_filter(text, results, allowlist, drop_types):
    """Principled filter: drop_types + word boundary + date surfaces +
    LOCATION rule + clinical allowlist. NO clinical-name regex — that load
    is carried by the OpenMed gate in the union engine."""
    kept = []
    for r in results:
        surface = text[r.start:r.end].strip()
        if r.entity_type in drop_types or not surface:
            continue
        if not _word_boundary_ok(text, r.start, r.end):
            continue
        if surface.lower() in allowlist:
            continue
        if r.entity_type == 'DATE_TIME' and _is_date_surface(surface):
            continue
        if (r.entity_type == 'DATE_TIME'
                and re.match(r'^\d{1,2}/\d{1,2}$', surface)
                and re.search(r'fraction\s*$',
                              text[max(0, r.start - 12):r.start], re.I)):
            continue
        if r.entity_type == 'LOCATION' and (
                len(surface) <= 3 or surface.islower()
                or re.match(r'^[A-Za-z]?-?\d[\w-]*$', surface)):
            continue
        kept.append(r)
    return kept


def _overlap(a, b, c, d):
    # intervals [a,b) and [c,d) overlap iff a < d and c < b
    return a < d and c < b


def union_deid(content, shift, S, RecognizerResult, openmed_rec, verbose=False,
               gate=True):
    """Approach C: union (spaCy+rules+OpenMed) for recall; OpenMed gates
    PERSON for clinical precision (a spaCy PERSON span survives only if
    OpenMed flagged a name overlapping it); dates shifted in code; repeated
    occurrences propagated. The brittle clinical-name regex bag is retired.

    gate=False: union WITHOUT the PERSON gate — spaCy keeps full recall
    (catches districts/names OpenMed misses), OpenMed adds recall (e.g. name
    variants), and the production filter carries precision. Used to compare
    'union+gate' vs 'union+filter'.
    """
    from django.conf import settings
    analyzer, _ = S._get_analyzer()
    thr = getattr(settings, 'EXTRACTOR_DEID_SCORE_THRESHOLD', 0.35)
    allowlist = {t.lower() for t in getattr(
        settings, 'EXTRACTOR_DEID_CLINICAL_ALLOWLIST', set())}
    drop_types = getattr(
        settings, 'EXTRACTOR_DEID_DROP_ENTITY_TYPES', {'ID', 'AGE', 'NRP'})

    spacy = analyzer.analyze(text=content, language='en', score_threshold=thr)
    om = openmed_rec.analyze(content)
    om_person = [(r.start, r.end) for r in om if r.entity_type == 'PERSON']

    def hit_person(r):
        return any(_overlap(r.start, r.end, a, b) for a, b in om_person)

    # precision: keep spaCy PERSON only where OpenMed also sees a name
    if gate:
        kept = [r for r in spacy if r.entity_type != 'PERSON' or hit_person(r)]
    else:
        kept = list(spacy)
    # recall: add OpenMed spans not already covered by kept
    kept_spans = [(r.start, r.end) for r in kept]

    def covered(r):
        return any(_overlap(r.start, r.end, a, b) for a, b in kept_spans)

    for r in om:
        if not covered(r):
            kept.append(r)

    if gate:
        filtered = _principled_filter(content, kept, allowlist, drop_types)
    else:
        filtered = S._filter_results(content, kept)
    filtered = S._resolve_overlaps(filtered)

    # propagate repeated occurrences, then re-resolve
    spans = [{'type': r.entity_type, 'start': r.start, 'end': r.end,
              'score': r.score} for r in filtered]
    spans = propagate_spans(content, spans)
    results = [RecognizerResult(entity_type=s['type'], start=s['start'],
                                end=s['end'], score=s.get('score', 0.9))
               for s in spans]
    results = S._resolve_overlaps(results)
    repl = []
    out = S._apply_replacements(content, results, shift, {}, repl)
    if verbose:
        print(f'    [union: spacy={len(spacy)} om={len(om)} '
              f'filtered={len(filtered)} final={len(results)}]')
    return out, 1, len(filtered)


def _minimal_filter(text, results):
    """Minimal filter: drop_types + word-boundary + date rules ONLY.

    No clinical vocabulary, no clinical-prefix regex, no allowlist, no
    LOCATION rules — those are exactly the 'brittle bag' under test. The
    LLM reviewer is expected to carry the clinical-precision load that the
    bag used to carry.
    """
    from django.conf import settings
    drop_types = getattr(
        settings, 'EXTRACTOR_DEID_DROP_ENTITY_TYPES', {'ID', 'AGE', 'NRP'})
    kept = []
    for r in results:
        surface = text[r.start:r.end].strip()
        if r.entity_type in drop_types or not surface:
            continue
        raw = text[r.start:r.end]
        b_start = r.start + (len(raw) - len(raw.lstrip()))
        b_end = r.end - (len(raw) - len(raw.rstrip()))
        if (b_start > 0 and text[b_start - 1].isalnum()) or \
                (b_end < len(text) and text[b_end].isalnum()):
            continue
        if r.entity_type == 'DATE_TIME' and re.match(
                r'^\d{1,3}%?$'
                r'|^(?:age\b:?\s*)?\d{1,3}\s*[-\s]?(years?\s+old|yrs?\s+old|years?|yrs?|y/o|y\.o\.|-?year-?old)\.?$'
                r'|^age\b:?\s*\d{1,3}\s*(years?|yrs?)?\.?$'
                r'|^\d{1,3}\s*(years?|yrs?|y)?\s*/\s*[MF]\b\.?$'
                r'|^[MF]\s*/\s*\d{1,3}\s*(years?|yrs?|y)?\b\.?$'
                r'|^\d{1,3}(?:\s*-\s*\d{1,3})?\s+(years?|months?|mnths?|mths?|mos?|weeks?|wks?|days?|hrs?|hours?|mins?|minutes?)\b\.?$'
                r'|^\d{1,3}\s*/\s*min\b\.?$'
                r'|^\d{1,2}:\d{2}$'
                r'|^[a-z][a-z]+\s+\d+(?:\.\d+)?\s*(g|mg|gm|ml)?\b\.?$',
                surface, re.I):
            continue
        if (r.entity_type == 'DATE_TIME'
                and re.match(r'^\d{1,2}/\d{1,2}$', surface)
                and re.search(r'fraction\s*$',
                              text[max(0, r.start - 12):r.start], re.I)):
            continue
        kept.append(r)
    return kept


def review_deid(content, shift, S, RecognizerResult, llm_chat, verbose=False,
                minimal_base=False):
    """Approach D: base deid (spaCy+rules) + LLM review corrections."""
    if minimal_base:
        from django.conf import settings
        analyzer, _ = S._get_analyzer()
        results = analyzer.analyze(
            text=content, language='en',
            score_threshold=getattr(
                settings, 'EXTRACTOR_DEID_SCORE_THRESHOLD', 0.35))
        results = S._resolve_overlaps(_minimal_filter(content, results))
        repl = []
        deid_text = S._apply_replacements(content, results, shift, {}, repl)
    else:
        deid_text, _counts, repl = S._deidentify_text(
            content, shift, None, ner_recognizer=None)
    ident = ('\n'.join(
        f"{e['tag']} = \"{e['original']}\" [{e['type']}]" for e in repl)
        if repl else '(none)')
    user = (f'DE-IDENTIFIED NOTE:\n{deid_text}\n\n===\n'
            f'IDENTIFIED LIST:\n{ident}')
    try:
        missed, restored = _parse_review_output(llm_chat(REVIEW_SYSTEM_PROMPT,
                                                         user))
    except ValueError as e:
        if verbose:
            print(f'    [review parse failed: {e}]')
        return deid_text, 1, 0

    # (A) restore over-redacted clinical content (verbatim tag lookup).
    norm_repl = {_norm(e['original']): e for e in repl}
    n_applied = 0
    for item in restored:
        e = norm_repl.get(_norm(item))
        if e and e['tag'] in deid_text:
            deid_text = deid_text.replace(e['tag'], e['original'])
            n_applied += 1

    # (B) redact missed PII (verbatim span in the deid text), guarded by the
    # production filter so ages/durations/clinical terms are not re-redacted.
    for raw_type, item in missed:
        etype = REVIEW_TYPE_MAP.get(_norm(raw_type).replace(' ', '_'),
                                   'PERSON')
        idx = deid_text.find(item)
        if idx == -1:
            idx = deid_text.lower().find(_norm(item)) if _norm(item) else -1
            if idx == -1:
                continue
            end = idx + len(_norm(item))
        else:
            end = idx + len(item)
        candidate = RecognizerResult(entity_type=etype, start=idx, end=end,
                                    score=0.9)
        if not S._filter_results(deid_text, [candidate]):
            continue  # production filter rejects it (age/clinical/etc.)
        n_existing = len(re.findall(rf'<{etype}_\d+>', deid_text))
        tag = f'<{etype}_{n_existing + 1}>'
        deid_text = deid_text[:idx] + tag + deid_text[end:]
        n_applied += 1

    if verbose:
        print(f'    [review: missed={len(missed)} restored={len(restored)} '
              f'applied={n_applied}]')
    return deid_text, 1, n_applied


# ---------------------------------------------------------------------------
# Approach B runner (reuses production redaction + date shift)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Approach E: System-1 (Jev-style) per-tag judge.
#
#   Local decision model (nimble) answers, per spaCy candidate tag, whether
#   the span is PHI (noul) and, if so, its type (serial noul questions, spaCy's
#   own type first). It sees the tag plus the surrounding sentences, so it
#   keeps clinical terms / durations / ages and redacts real PII — replacing
#   the brittle clinical-regex filter. Dates are shifted in code.
#
#   Two stages per tag:
#     DATE_TIME  -> 1 noul: "calendar date?"  (yes=shift in code, no=keep)
#     other      -> Stage 1 noul: "is this PHI?"  (no=keep)
#                   Stage 2 noul: serial type questions, spaCy type first
# ---------------------------------------------------------------------------

SYSTEMONE_URL = 'http://localhost:11434/v1/systemone'
SYSTEMONE_MODEL = 'nimble'
PHI_THRESHOLD = 0.5     # noul >= this -> deidentify
TYPE_THRESHOLD = 0.25   # min noul to trust a Stage-2 type answer

CAT_ORDER = ['PERSON', 'LOCATION', 'ORGANIZATION', 'PHONE', 'ID', 'DATE_TIME']

CAT_Q = {
    'PERSON': ('a person\'s name (the patient, a relative, or a doctor/staff '
               'member)?'),
    'LOCATION': ('a location or address (village, town, city, state, street, '
                 'or house)?'),
    'ORGANIZATION': ('an organisation such as a hospital, clinic, laboratory, '
                     'or department?'),
    'PHONE': 'a telephone or mobile number?',
    'ID': ('an identifier number (medical record number, Aadhaar, ABHA, PIN '
           'code, UPI, registration/report/case number, or driving licence)?'),
    'DATE_TIME': ('a calendar date or a specific point in time (a day, month, '
                  'or year)?'),
}

_ID_TYPES = {
    'MEDICAL_RECORD_NUMBER', 'IN_AADHAAR', 'IN_MOBILE_NUMBER', 'IN_PINCODE',
    'IN_ABHA', 'IN_UPI', 'IN_DRIVING_LICENSE', 'IN_NATIONAL_ID', 'IN_PASSPORT',
    'IN_BANK_NUMBER', 'IN_IBAN', 'IN_SOCIAL_SECURITY_NUMBER', 'IN_CREDIT_CARD',
    'PATIENT_ID',
}


def _spacy_to_cat(etype):
    if etype == 'PERSON':
        return 'PERSON'
    if etype == 'LOCATION':
        return 'LOCATION'
    if etype == 'ORGANIZATION':
        return 'ORGANIZATION'
    if etype in ('PHONE_NUMBER', 'IN_MOBILE_NUMBER'):
        return 'PHONE'
    if etype in _ID_TYPES:
        return 'ID'
    if etype == 'DATE_TIME':
        return 'DATE_TIME'
    return 'ID'


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


def _build_context(text, start, end):
    """The tag plus surrounding sentences, with the span marked «...»."""
    surf = text[start:end]
    ws = max(0, start - 250)
    we = min(len(text), end + 250)
    excerpt = text[ws:we]
    rel = start - ws
    return excerpt[:rel] + '«' + surf + '»' + excerpt[rel + len(surf):]


def judge_tag(text, start, end, spacy_type):
    """Judge one spaCy candidate tag. Returns (presidio_type_or_None, p, calls).
    None == 'keep, do not de-identify'."""
    state = {'excerpt': _build_context(text, start, end)}
    cat = _spacy_to_cat(spacy_type)
    if cat == 'DATE_TIME':
        # One question: real date (-> code shifts) vs duration/age (-> keep).
        ans = _so_post(state, {'is_date': {
            'type': 'noul',
            'instructions': ('Is the span marked «...» a calendar date or a '
                             'specific point in time (a day, month, or year) '
                             '— as opposed to a duration/interval such as '
                             '"1 month" or an age such as "56 years"?')}})
        p = _so_noul(ans, 'is_date')
        return ('DATE_TIME' if p >= PHI_THRESHOLD else None, p, 1)
    # Stage 1: is this PHI that should be de-identified?
    ans1 = _so_post(state, {'is_phi': {
        'type': 'noul',
        'instructions': ('Is the span marked «...» personally identifiable or '
                         'private medical information that should be '
                         'de-identified from this clinical note? Names of '
                         'people, locations/addresses, organisations, phone '
                         'or ID numbers, and calendar dates count. Diagnoses, '
                         'medications, doses, lab values, vitals, '
                         'durations/intervals, and ages do not.')}})
    p = _so_noul(ans1, 'is_phi')
    if p < PHI_THRESHOLD:
        return (None, p, 1)
    # Stage 2: serial type questions, spaCy's own type first.
    order = [cat] + [c for c in CAT_ORDER if c != cat]
    q2 = {f't_{c}': {'type': 'noul',
                     'instructions': 'Is the span marked «...» ' + CAT_Q[c]}
          for c in order}
    ans2 = _so_post(state, q2)
    scores = {c: _so_noul(ans2, f't_{c}') for c in order}
    best = max(scores, key=scores.get)
    if scores[best] < TYPE_THRESHOLD:
        best = cat  # not confident -> trust spaCy's type
    if best == 'ID':
        return (spacy_type, p, 2)      # keep the specific ID subtype
    if best == 'PHONE':
        return ('PHONE_NUMBER', p, 2)
    return (best, p, 2)


def systemone_deid(content, shift, S, RecognizerResult, verbose=False):
    """Approach E: spaCy+rules candidates, each judged by the local System-1
    model (per-tag, with context). The judge replaces the clinical-regex
    filter; dates are shifted in code; repeated occurrences propagated."""
    from django.conf import settings
    analyzer, _ = S._get_analyzer()
    thr = getattr(settings, 'EXTRACTOR_DEID_SCORE_THRESHOLD', 0.35)
    raw = analyzer.analyze(text=content, language='en', score_threshold=thr)
    seen, cands = set(), []
    for r in raw:
        key = (r.start, r.end)
        if key in seen:
            continue
        seen.add(key)
        cands.append((r.entity_type, r.start, r.end))
    kept, calls = [], 0
    for etype, s, e in cands:
        pres_type, p, ncalls = judge_tag(content, s, e, etype)
        calls += ncalls
        if verbose:
            print(f'    [judge {etype:22s} {content[s:e]!r:26s} '
                  f'p={p:.2f} -> {pres_type}]')
        if pres_type is None:
            continue
        kept.append({'type': pres_type, 'start': s, 'end': e, 'score': 0.9})
    kept = propagate_spans(content, kept)
    results = [RecognizerResult(entity_type=s['type'], start=s['start'],
                                end=s['end'], score=s.get('score', 0.9))
               for s in kept]
    results = S._resolve_overlaps(results)
    repl = []
    out = S._apply_replacements(content, results, shift, {}, repl)
    if verbose:
        print(f'    [systemone: cands={len(cands)} kept={len(results)} '
              f'calls={calls}]')
    return out, calls, len(cands) - len(results)


def run():
    ap = argparse.ArgumentParser()
    ap.add_argument('--engine', default='llm',
                    choices=['llm', 'openmed', 'review', 'union', 'systemone'],
                    help='llm = multi-pass gemma; openmed = single-pass '
                         'clinical NER; review = spaCy+rules base + LLM '
                         'reviewer; union = spaCy+rules+OpenMed union; '
                         'systemone = spaCy+rules candidates, per-tag nimble '
                         'System-1 judge (dates in code)')
    ap.add_argument('--passes', type=int, default=3,
                    help='max passes (llm engine only; 1 = baseline)')
    ap.add_argument('--no-safenet', action='store_true')
    ap.add_argument('--nogate', action='store_true',
                    help='union engine only: skip the OpenMed PERSON gate '
                         '(spaCy keeps full recall; production filter '
                         'carries precision)')
    ap.add_argument('--minimal-base', action='store_true',
                    help='review engine only: base deid uses the minimal '
                         'filter (no clinical-regex bag)')
    ap.add_argument('--only', default=None)
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chavi_client.settings')
    import django
    django.setup()
    from presidio_analyzer import RecognizerResult
    from extractor.models import ClientConfiguration
    from extractor.services.text_deidentification import (
        TextDeidentificationService as S)

    use_safenet = not args.no_safenet
    docs = [d for d in DOCS if args.only is None or args.only in d[0]]

    if args.engine == 'llm':
        from extractor.services.llm_ner import LlmNerClient
        cfg = ClientConfiguration.objects.get(llm_model_name='gemma4:e2b')
        llm = LlmNerClient(cfg)

        def identify(text):
            """Multi-pass LLM identification (independent passes on the
            original; pass 2 checks for extra, pass 3 finalizes)."""
            t0 = time.monotonic()
            s1 = llm.find_entities_in_text(text)
            if use_safenet:
                s1 = s1 + safenet_spans(text)
            calls, passes_used = 1, 1
            union = {(s['type'], s['start'], s['end']): s for s in s1}
            extra = []
            if args.passes >= 2:
                s2 = llm.find_entities_in_text(text)
                if use_safenet:
                    s2 = s2 + safenet_spans(text)
                calls += 1
                passes_used = 2
                extra = [s for s in s2
                         if (s['type'], s['start'], s['end']) not in union]
                s3 = []
                if extra and args.passes >= 3:
                    s3 = llm.find_entities_in_text(text)
                    if use_safenet:
                        s3 = s3 + safenet_spans(text)
                    calls += 1
                    passes_used = 3
                for s in s2 + s3:
                    union[(s['type'], s['start'], s['end'])] = s
            return list(union.values()), calls, passes_used, extra, t0

        eng_desc = f'llm multi-pass<={args.passes}'
    elif args.engine == 'openmed':
        from extractor.services.openmed_ner import OpenMedNerRecognizer
        rec = OpenMedNerRecognizer()

        def identify(text):
            """Single deterministic OpenMed pass (true offsets)."""
            t0 = time.monotonic()
            r = rec.analyze(text)
            spans = [{'type': x.entity_type, 'start': x.start, 'end': x.end,
                      'score': x.score} for x in r]
            if use_safenet:
                spans = spans + safenet_spans(text)
            return spans, 1, 1, [], t0

        eng_desc = 'openmed single-pass'
    elif args.engine == 'review':
        from openai import OpenAI
        cfg = ClientConfiguration.objects.get(llm_model_name='gemma4:e2b')
        review_client = OpenAI(base_url='http://localhost:11434/v1',
                               api_key='ollama', timeout=cfg.request_timeout)

        def llm_chat(system, user):
            c = review_client.chat.completions.create(
                model='gemma4:e2b', temperature=0, max_tokens=2048,
                messages=[{'role': 'system', 'content': system},
                          {'role': 'user', 'content': user}])
            return c.choices[0].message.content or ''

        def identify(_text):
            raise NotImplementedError  # review path does not use identify()

        eng_desc = 'review (spaCy+rules base + LLM reviewer, dates ignored)'
    elif args.engine == 'union':
        from extractor.services.openmed_ner import OpenMedNerRecognizer
        union_om = OpenMedNerRecognizer()

        def identify(_text):
            raise NotImplementedError  # union path does not use identify()

        eng_desc = ('union (spaCy+rules+OpenMed) + OpenMed PERSON gate '
                    '+ code date shift')
    elif args.engine == 'systemone':
        def identify(_text):
            raise NotImplementedError  # systemone path does not use identify()

        eng_desc = ('systemone (spaCy+rules candidates, per-tag nimble '
                    'judge with context; replaces clinical filter)')

    print(f'Approach ({eng_desc}) | '
          f'safenet={"on" if use_safenet else "off"} docs={len(docs)}')

    def deid_from_spans(text, span_list, shift):
        """Union spans -> propagate -> production filter/overlap/replace."""
        seen, deduped = set(), []
        for s in span_list:
            key = (s['type'], s['start'], s['end'])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(s)
        span_list = propagate_spans(text, deduped)
        results = [RecognizerResult(
            entity_type=s['type'], start=s['start'], end=s['end'],
            score=s.get('score', 0.9)) for s in span_list]
        results = S._resolve_overlaps(S._filter_results(text, results))
        repl = []
        out = S._apply_replacements(text, results, shift, {}, repl)
        return out

    # aggregation per config
    agg = {'leaks': 0, 'lost': 0, 'unshifted': 0, 'secs': 0.0,
           'calls': 0, 'extra_found': 0}
    for doc_name, content, _ext in docs:
        random.seed(doc_name)          # same shift for a given doc
        shift = random.randint(-45, 45) or 15
        t0 = time.monotonic()
        if args.engine == 'review':
            out, calls, extra = review_deid(
                content, shift, S, RecognizerResult, llm_chat,
                verbose=not args.quiet, minimal_base=args.minimal_base)
        elif args.engine == 'union':
            out, calls, extra = union_deid(
                content, shift, S, RecognizerResult, union_om,
                verbose=not args.quiet, gate=not args.nogate)
        elif args.engine == 'systemone':
            out, calls, extra = systemone_deid(
                content, shift, S, RecognizerResult,
                verbose=not args.quiet)
        else:
            span_list, calls, _passes_used, extra, _t0 = identify(content)
            out = deid_from_spans(content, span_list, shift)
        secs = time.monotonic() - t0
        leaks, lost, unshifted = score(content, out)

        agg['leaks'] += len(leaks)
        agg['lost'] += len(lost)
        agg['unshifted'] += len(unshifted)
        agg['secs'] += secs
        agg['calls'] += calls
        agg['extra_found'] += 1 if extra else 0

        if not args.quiet:
            print(f'  {doc_name[:42]:44s} {secs:5.1f}s {calls} call(s) '
                  f'leaks={len(leaks)} lost={len(lost)} '
                  f'unshifted={len(unshifted)}')
            for label, items in (('leaks', leaks), ('lost', lost),
                                 ('unshifted', unshifted)):
                if items:
                    print(f'          {label}: {items}')

    n = len(docs)
    print('\n' + '=' * 70)
    print(f'APPROACH B SUMMARY  engine={args.engine}  '
          f'safenet={"on" if use_safenet else "off"}  docs={n}')
    print('=' * 70)
    print(f'  leaks={agg["leaks"]:3d}   lost={agg["lost"]:3d}   '
          f'unshifted={agg["unshifted"]:3d}')
    print(f'  total_time={agg["secs"]:.0f}s   '
          f'avg_identify_calls={agg["calls"] / n:.1f}')


if __name__ == '__main__':
    run()
