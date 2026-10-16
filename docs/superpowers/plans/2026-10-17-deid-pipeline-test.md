# De-Identification Pipeline Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a staged, like-with-like comparison harness for the extractor text-de-identification pipeline and run a sequential test — traditional NER first, then LLM addition, then precision — to find the best CPU-only pipeline for realistic short Indian clinical notes, with full results documented.

**Architecture:** The harness decouples the three orthogonal jobs of de-identification — **Recall** (which detectors find candidate spans), **Precision** (which keep/drop mechanism redacts-vs-keeps), and **Dates** (duration/age vs real-date handling) — and varies exactly one axis per stage. The production `_filter_results` is decomposed into `_filter_mechanical` + `_filter_dates` + `_filter_clinical` (behaviour-preserving) so Precision (P1 vs P2) can be tested with Dates (T0) held constant. Candidates are precomputed and cached per recall config so later stages reuse them.

**Tech Stack:** Python (Django `venv`), Presidio `AnalyzerEngine`, spaCy, Stanford NER (HF `stanford-deidentifier-base`), Ollama local models (`gemma4:e2b` NER, `nimble` System-1 judge via `/v1/systemone`), OpenMed `pii_superclinical_large`, the existing ground-truth catalog of 14 realistic notes.

**Spec:** The staged test design in the "Test Design" section below (the plan argues from it) plus `docs/superpowers/plans/2026-10-15-llm-ner-deid.md` (production de-identification context).

## Global Constraints

- **CPU-only** models: `gemma4:e2b` (\~4.6B), OpenMed `pii_superclinical_large` (\~4.6B), `nimble` (System-1). No GPU; `gemma4:26b` is NOT to be used.
- **Do NOT change the default production pipeline.** The decomposition of `_filter_results` must be behaviour-preserving: `_filter_results(text, results)` must return the same spans it does today. The default (R3 + P1 + T0) stays the shipped engine.
- **Ground truth** is the fixed catalog of **14 notes** (3 synthetic + 11 field) with per-note `PII_TOKENS`, `CLINICAL_TOKENS`, and the date list `DATES`. It is the single source of truth — extracted into `scripts/deid_ground_truth.py`.
- **Metrics** (per note, aggregated across notes):
  - `leaks` — PII tokens present in source **and** surviving in output. Lower is better. (privacy)
  - `lost` — CLINICAL\_TOKENS present in source **and** absent in output (over-redacted). Lower is better. (utility)
  - `unshifted` — real `DATES` present in source **and** still appearing verbatim in output. Lower is better.
  - A config wins on the tuple `(leaks, lost, unshifted)` compared lexicographically (lowest first).
- **Scoring semantics** are inherited verbatim from `scripts/ab_deid_test.py` / `scripts/deid_approach_b.py` (lowercase substring containment; `unshifted` is a known conservative artifact — a short date substring may match inside a shifted longer date). Do not change scoring mid-test.
- **Dates are always T0** (code-based): durations/ages survive (never redacted), real dates shift. Nimble dates (T1) are OUT of scope for this test per the agreed design.
- **Python:** `venv/bin/python` (Python 3.13). **Tests:** `venv/bin/python manage.py test extractor -v 1 --noinput`.
- **Known pre-existing test failures (ignore, not caused by this work):** `test_invalid_assessments_rejected`, `test_resolve_overlaps_keeps_highest_score`.
- **Ollama** is at `http://localhost:11434`; `nimble` uses the `/v1/systemone` endpoint; `gemma4:e2b` uses OpenAI-compat `/v1/chat/completions`.
- **Parallelism:** all models are local and share one CPU (12 cores) + one Ollama server. Only **Stage 1** (pure in-process spaCy/Stanford NER) benefits from parallel processes. LLM stages (gemma/nimble) are Ollama-bound and must run sequentially.

## File Structure

- `scripts/deid_ground_truth.py` — **Create.** Single source of truth for the test data and shared utilities: `DOCS`, `PII_TOKENS`, `CLINICAL_TOKENS`, `DATES`, `score()`, `propagate_spans()`, `PROPAGATE_TYPES`, `build_safenet_spans()`. Importable without side effects (no `main()` gate needed, but guard any top-level work).
- `scripts/pipeline_test.py` — **Create.** The staged harness: builds candidates for a recall config, applies mechanical + T0 dates + precision (P1/P2), propagates, resolves overlaps, applies replacements, scores, caches candidates, and reports per-note + aggregate. CLI: `--config R3+gemma --precision P1 --out results.json [--only SUBSTR] [--verbose]`.
- `extractor/services/text_deidentification.py` — **Modify.** Decompose `_filter_results` into `_filter_mechanical` + `_filter_dates` + `_filter_clinical`; keep `_filter_results` as the composition (behaviour-preserving).
- `extractor/tests.py` — **Modify.** Add tests proving the decomposed `_filter_results` equals the original behaviour, plus unit tests for each sub-filter.
- `scripts/ab_deid_test.py` — **Modify.** Replace the inline catalog (`DOCS`, `PII_TOKENS`, …) with `from scripts.deid_ground_truth import …` (or the equivalent import) so there is one source of truth.
- `scripts/deid_approach_b.py` — **Modify.** Replace `load_catalog()` + local `score`/`propagate_spans` with imports from `scripts/deid_ground_truth.py`.
- `docs/superpowers/plans/2026-10-17-deid-pipeline-test.md` — **This file.** Test design + tasks + a `## Results` section filled in as each stage runs.

## Test Design (the spec)

### Axes

**Recall (R) — detector union, rules always on:**


| Name       | Detectors                                   | Built as                                                |
| ---------- | ------------------------------------------- | ------------------------------------------------------- |
| R1         | spaCy + rules                               | `_build_analyzer(include_hf_ner=False, slim_ner=False)` |
| R2         | Stanford + rules (no spaCy NER)             | `_build_analyzer(include_hf_ner=True, slim_ner=True)`   |
| R3         | spaCy + Stanford + rules (current default)  | `_build_analyzer(include_hf_ner=True, slim_ner=False)`  |
| `+gemma`   | R-variant + `LlmNerRecognizer` (ad-hoc)     | Stage 2 addition                                        |
| `+OpenMed` | R-variant + `OpenMedNerRecognizer` (ad-hoc) | Stage 2 addition                                        |


**Precision (P) — keep/drop per candidate (applied after mechanical + T0):**


| Name | Mechanism                                                                                                                           |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------- |
| P1   | production clinical filter (`_filter_clinical`: allowlist + clinical-prefix + LOCATION rules)                                       |
| P2   | `nimble` System-1 judge — per non-date candidate, "is this PHI?" (keep if score ≥ 0.5); dates skip the judge and shift in code (T0) |


**Dates (T):** always **T0** (`_filter_dates`: drop duration/age surfaces, keep real dates to be shifted). T1 (nimble dates) is out of scope.

### Stages (sequential; each varies one axis, holds the rest constant)

- **Stage 1 — Traditional NER.** `R1` vs `R2` vs `R3`, held `P1 + T0`. Winner = **W** on `(leaks, lost, unshifted)`.
- **Stage 2 — Add LLM to W.** `W` vs `W+gemma` vs `W+OpenMed`, held `P1 + T0`. Winner = **best recall** on `(leaks, lost, unshifted)`.
- **Stage 3 — Precision.** On the Stage-2 winner or Stage -1 winner (if any stage 2 performs better than stage 1), `P1` vs `P2`, held `T0`. Winner = **best precision** on `(leaks, lost, unshifted)`.
- **Stage 5 — Assemble.** Run `best_recall + best_precision + T0` end-to-end, confirm the numbers, and record the final recommendation.

### Apples-to-apples principle

Within a stage, **only the axis under test varies**. Everything else — the other detectors, the precision mechanism, date handling, and the mechanical post-processing (word-boundary, `propagate_spans`, `_resolve_overlaps`, `_apply_replacements`) — is held identical. Candidates for each recall config are computed once and cached (JSON) so the precision stage reuses the exact candidate set (no re-run of NER, no drift).

### Winner selection &amp; stopping

A stage is "done" when every config in it has a full 14-note result. The winner is chosen on the aggregated `(leaks, lost, unshifted)`. If a stage's winner is unchanged by the next stage's best addition (e.g. `+gemma` does not beat `W`), record that and move on. The test ends at Stage 5 with a single recommended config.

---

### Task 1: Decompose `_filter_results` into `_filter_mechanical` + `_filter_dates` + `_filter_clinical`

**Why:** the harness must test Precision (P1 vs P2) with Dates (T0) held constant. Today the clinical-precision rules and the date/duration rules are interleaved in one `_filter_results` monolith, so they cannot be varied independently. Decompose into three behaviour-preserving static methods; keep `_filter_results` as their composition so the shipped engine is unchanged.

**Files:**

- Modify: `extractor/services/text_deidentification.py:472-553` (the `_filter_results` staticmethod)
- Test: `extractor/tests.py` (new `FilterDecompositionTests`; the existing `DurationFilterTests`, `AgeDurationRegressionTests`, `ClinicalAllowlistTests` become the equivalence guard — they must pass unchanged)

**Interfaces:**

- Produces: `TextDeidentificationService._filter_mechanical(text, results)`, `_filter_dates(text, results)`, `_filter_clinical(text, results)` — each returns the list of `AnalysisResult`-shaped objects that survive that stage (same `.entity_type/.start/.end/.score` shape). `_filter_results(text, results)` unchanged in signature and behaviour.
- Consumes: `settings.EXTRACTOR_DEID_DROP_ENTITY_TYPES`, `settings.EXTRACTOR_DEID_CLINICAL_ALLOWLIST` (already used by `_filter_results`).

- [ ] **Step 1: Write the failing tests**

Append to `extractor/tests.py`:

```python
class FilterDecompositionTests(SimpleTestCase):
    """_filter_results is decomposed into mechanical + dates + clinical.

    Equivalence with the original monolith is proven by the pre-existing
    DurationFilterTests / AgeDurationRegressionTests / ClinicalAllowlistTests
    continuing to pass unchanged. These tests pin each sub-filter's job.
    """

    def _mk(self, etype, start, end):
        class R:
            def __init__(self):
                self.entity_type = etype
                self.start = start
                self.end = end
                self.score = 0.9
        return R()

    def test_mechanical_drops_drop_type_and_midword(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        text = "oropharynx"
        idr = self._mk('ID', 0, 2)        # in drop_types
        mid = self._mk('PERSON', 3, 6)    # 'oph' mid-word
        ok = self._mk('PERSON', 0, 10)    # whole token, kept
        kept = S._filter_mechanical(text, [idr, mid, ok])
        self.assertEqual([r.entity_type for r in kept], ['PERSON'])

    def test_dates_drops_duration_keeps_real_date(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        text = "for 1 month admitted 01/02/2024"
        dur = self._mk('DATE_TIME', text.find('1 month'), text.find('1 month') + 7)
        real = self._mk('DATE_TIME', text.find('01/02/2024'), text.find('01/02/2024') + 10)
        kept = S._filter_dates(text, [dur, real])
        self.assertEqual([text[r.start:r.end] for r in kept], ['01/02/2024'])

    def test_clinical_drops_lab_keeps_name(self):
        from extractor.services.text_deidentification import (
            TextDeidentificationService as S)
        text = "Hb 9.8 seen Taboo Singh"
        lab = self._mk('PERSON', 0, 6)    # 'Hb 9.8' clinical prefix
        name = self._mk('PERSON', text.find('Taboo Singh'), text.find('Taboo Singh') + 11)
        kept = S._filter_clinical(text, [lab, name])
        self.assertEqual([text[r.start:r.end] for r in kept], ['Taboo Singh'])
```

- [ ] **Step 2: Run the tests to confirm they fail**

Run: `venv/bin/python manage.py test extractor.FilterDecompositionTests -v 2 --noinput`
Expected: 3 FAIL with `AttributeError: ... has no attribute '_filter_mechanical'` (and `_filter_dates`, `_filter_clinical`).

- [ ] **Step 3: Implement the decomposition**

In `extractor/services/text_deidentification.py`, replace the single `_filter_results` body with three static methods plus a composing `_filter_results`. Preserve every regex and condition **verbatim** from the current monolith — only move code between methods. Split of the current per-result checks:

- `_filter_mechanical(text, results)` — `drop_types`, empty-surface, and mid-word-boundary checks.
- `_filter_dates(text, results)` — the `DATE_TIME` date/duration/age/pulse/dose regex (`re.match(..., surface, re.I)`) and the fraction-counter lookbehind.
- `_filter_clinical(text, results)` — the `allowlist` membership, the PERSON/ORGANIZATION clinical-prefix regex, and the LOCATION short/lowercase/label rule.

```python
    @staticmethod
    def _filter_mechanical(text, results):
        drop_types = getattr(
            settings, 'EXTRACTOR_DEID_DROP_ENTITY_TYPES', {'ID', 'AGE', 'NRP'})
        kept = []
        for r in results:
            surface = text[r.start:r.end].strip()
            if r.entity_type in drop_types:
                continue
            if not surface:
                continue
            raw = text[r.start:r.end]
            b_start = r.start + (len(raw) - len(raw.lstrip()))
            b_end = r.end - (len(raw) - len(raw.rstrip()))
            if (b_start > 0 and text[b_start - 1].isalnum()) or \
                    (b_end < len(text) and text[b_end].isalnum()):
                continue
            kept.append(r)
        return kept

    @staticmethod
    def _filter_dates(text, results):
        kept = []
        for r in results:
            surface = text[r.start:r.end].strip()
            if (r.entity_type == 'DATE_TIME' and re.match(
                    r'^\d{1,3}%?$'
                    r'|^(?:age\b:?\s*)?\d{1,3}\s*[-\s]?(years?\s+old|yrs?\s+old|years?|yrs?|y/o|y\.o\.|year-?old)\.?$'
                    r'|^age\b:?\s*\d{1,3}\s*(years?|yrs?)?\.?$'
                    r'|^\d{1,3}\s*(years?|yrs?|y)?\s*/\s*[MF]\b\.?$'
                    r'|^[MF]\s*/\s*\d{1,3}\s*(years?|yrs?|y)?\b\.?$'
                    r'|^\d{1,3}(?:\s*-\s*\d{1,3})?\s+(years?|months?|mnths?|mths?|mos?|weeks?|wks?|days?|hrs?|hours?|mins?|minutes?)\b\.?$'
                    r'|^\d{1,3}\s*/\s*min\b\.?$'
                    r'|^\d{1,2}:\d{2}$'
                    r'|^(?!(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)\b)[a-z][a-z]+\s+\d+(?:\.\d+)?\s*(g|mg|gm|ml)?\b\.?$',
                    surface, re.I)):
                continue
            if (r.entity_type == 'DATE_TIME'
                    and re.match(r'^\d{1,2}/\d{1,2}$', surface)
                    and re.search(r'fraction\s*$',
                                  text[max(0, r.start - 12):r.start], re.I)):
                continue
            kept.append(r)
        return kept

    @staticmethod
    def _filter_clinical(text, results):
        allowlist = {
            t.lower() for t in getattr(
                settings, 'EXTRACTOR_DEID_CLINICAL_ALLOWLIST', set())}
        kept = []
        for r in results:
            surface = text[r.start:r.end].strip()
            if surface.lower() in allowlist:
                continue
            if r.entity_type in ('PERSON', 'ORGANIZATION') and re.match(
                    r'^(hb|h\.b\.?|tabs?\b|inj\b|caps?\b|iv\b|po\b|oral\b|spo2?|s\.p\.o|jvp|ef\b|bp\b|pr\b|hr\b|wt\b|lmp\b)',
                    surface, re.I):
                continue
            if r.entity_type == 'LOCATION':
                if (len(surface) <= 3 or surface.islower()
                        or re.match(r'^[A-Za-z]?-?\d[\w-]*$', surface)):
                    continue
            kept.append(r)
        return kept

    @staticmethod
    def _filter_results(text, results):
        """Composition of mechanical + dates + clinical (== original).

        Dropped iff any stage drops, so the survivors are identical to the
        previous single-loop monolith regardless of composition order.
        """
        results = TextDeidentificationService._filter_mechanical(text, results)
        results = TextDeidentificationService._filter_dates(text, results)
        results = TextDeidentificationService._filter_clinical(text, results)
        return results
```

> **Caution:** copy the DATE\_TIME and clinical-prefix regexes byte-for-byte from the current `_filter_results`. A single character drift (e.g. the month-name negative lookahead) silently changes behaviour. Do not "clean up" the regexes.

- [ ] **Step 4: Run the full extractor suite to confirm equivalence**

Run: `venv/bin/python manage.py test extractor -v 1 --noinput`
Expected: the 3 new `FilterDecompositionTests` pass; ALL pre-existing filter tests (`DurationFilterTests`, `AgeDurationRegressionTests`, `ClinicalAllowlistTests`, `DeidReplacementTests`) still pass. Only the 2 known pre-existing failures remain (`test_invalid_assessments_rejected`, `test_resolve_overlaps_keeps_highest_score`).

- [ ] **Step 5: Commit**

```bash
git add extractor/services/text_deidentification.py extractor/tests.py
git commit -m "refactor(deid): decompose _filter_results into mechanical/dates/clinical"
```

---

### Task 2: Extract the ground-truth catalog into `scripts/deid_ground_truth.py`

**Why:** the 14-note catalog + scoring + propagation live inline in `ab_deid_test.py` and are copied via `exec`-slicing in `deid_approach_b.py`. The staged harness needs a single importable source of truth. Move it out so all scripts import one module.

**Files:**

- Create: `scripts/deid_ground_truth.py`
- Modify: `scripts/ab_deid_test.py` (lines 43-595 → import)
- Modify: `scripts/deid_approach_b.py` (replace `load_catalog()` + local `score`/`propagate_spans` with imports)

**Interfaces:**

- Produces (module-level, importable without Django or Ollama): `DOCS` (list of `(name, content, ext)`), `PII_TOKENS`, `CLINICAL_TOKENS`, `DATES` (all `list[str]`); `score(source, out) -> (leaks, lost, unshifted)`; `propagate_spans(text, span_list) -> list[dict]`; `PROPAGATE_TYPES` (set); `build_safenet_spans(text) -> list[dict]`.

- [ ] **Step 1: Create `scripts/deid_ground_truth.py` with the data moved verbatim**

Move **lines 43-595** of `scripts/ab_deid_test.py` (the doc content strings, `DOCS_CLEAN`, `DOCS_REALISTIC`, `DOCS`, `PII_TOKENS`, `CLINICAL_TOKENS`, `DATES`) into the new file verbatim. Prepend a header and `import re`. Then append `propagate_spans`, `PROPAGATE_TYPES` (from `scripts/deid_approach_b.py:76-122`), `score` (from `deid_approach_b.py:124-129`), and `SAFENET` + `build_safenet_spans` (from `deid_approach_b.py:60-73`, renaming `safenet_spans` → `build_safenet_spans`).

> Copy the data and functions verbatim — do not rewrite the token lists or the note contents.

- [ ] **Step 2: Verify the module loads and the catalog is intact**

Run: `venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); import deid_ground_truth as g; print(len(g.DOCS), len(g.PII_TOKENS), len(g.CLINICAL_TOKENS), len(g.DATES))"`
Expected: `14 ...`. Record these four counts as the reference numbers.

- [ ] **Step 3: Point `ab_deid_test.py` at the shared module**

In `scripts/ab_deid_test.py`, delete lines 43-595 (the catalog) and, after the existing `import` block, add:

```python
from deid_ground_truth import (DOCS, PII_TOKENS, CLINICAL_TOKENS, DATES)
```

(Grep for `DOC_` first; only keep the content strings in `ab_deid_test.py` if later code references them directly.)

- [ ] **Step 4: Point `deid_approach_b.py` at the shared module**

In `scripts/deid_approach_b.py`, replace the `load_catalog()` function, the `DOCS, PII_TOKENS, CLINICAL_TOKENS, DATES = load_catalog()` line, and the local `score`, `propagate_spans`, `PROPAGATE_TYPES`, and `SAFENET`/`safenet_spans` definitions with:

```python
from deid_ground_truth import (DOCS, PII_TOKENS, CLINICAL_TOKENS, DATES,
                               score, propagate_spans, PROPAGATE_TYPES,
                               build_safenet_spans)
```

Update any `safenet_spans(` call sites to `build_safenet_spans(`.

- [ ] **Step 5: Verify both scripts still load 14 docs and import cleanly**

Run:

```
venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); import ab_deid_test; print('ab', len(ab_deid_test.DOCS))"
venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); import deid_approach_b; print('ab2', len(deid_approach_b.DOCS))"
```

Expected: `ab 14` and `ab2 14`. Importing `deid_approach_b` must not trigger Ollama/model calls (`main()` is behind the `__main__` guard).

- [ ] **Step 6: Commit**

```bash
git add scripts/deid_ground_truth.py scripts/ab_deid_test.py scripts/deid_approach_b.py
git commit -m "test(deid): extract ground-truth catalog into deid_ground_truth"
```

---

### Task 3: Build the staged harness `scripts/pipeline_test.py`

**Why:** one CLI that runs any `(recall config, precision)` over all 14 notes, scores, and reports. It decouples recall (detector union) from precision (P1/P2) so each stage varies exactly one axis. Candidates are cached to disk (keyed by recall config + note) so the precision stage reuses the exact candidate set and no NER runs twice.

**Files:**

- Create: `scripts/pipeline_test.py`
- Create: `scripts/.cache/` (git-ignored; candidate cache)

**Interfaces:**

- Consumes: `S._build_analyzer(include_hf_ner, slim_ner)` (classmethod), `S._filter_results/_filter_mechanical/_filter_dates`, `S._resolve_overlaps`, `S._apply_replacements`, `LlmNerRecognizer`, `OpenMedNerRecognizer`, `deid_ground_truth.{DOCS,score,propagate_spans}`.
- Produces: CLI `pipeline_test.py --config <R[123](+gemma|+openmed)?> --precision P1|P2 [--only SUBSTR] [--out F.json] [--verbose] [--no-cache]`.

- [ ] **Step 1: Add `scripts/.cache/` to `.gitignore`**

Append to `.gitignore`:

```gitignore
scripts/.cache/
```

- [ ] **Step 2: Write the harness**

Create `scripts/pipeline_test.py`:

```python
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
        SYSTEMONE_URL, data=payload, headers={'Content-Type': 'application/json'})
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
    return os.path.join(CACHE_DIR, 'cands_' + config.replace('+', '_') + '.json')


class _Cand:
    def __init__(self, t, a, b, sc):
        self.entity_type, self.start, self.end, self.score = t, a, b, sc


def gen_candidates(content, config, use_cache):
    base, adds = parse_config(config)
    path = _cache_path(config)
    if use_cache and os.path.exists(path):
        rows = json.load(open(path))
        by_name = {r['name']: r['cands'] for r in rows}
        if name_of(content) in by_name:
            return [_Cand(*c) for c in by_name[name_of(content)]]
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


def name_of(content):
    for name, c, _ in DOCS:
        if c == content:
            return name
    raise ValueError('content not in catalog')


def _upsert_cache(path, name, cands):
    rows = json.load(open(path)) if os.path.exists(path) else []
    rows = [r for r in rows if r['name'] != name]
    rows.append({'name': name, 'cands': cands})
    json.dump(rows, open(path, 'w'))


# --- precision + application ---
def apply_precision(content, cands, precision, verbose=False):
    if precision == 'P1':
        return S._filter_results(content, cands)  # monolith == production
    # P2: mechanical + dates (same as production) + nimble (replaces clinical)
    cands = S._filter_mechanical(content, cands)
    kept = []
    for r in cands:
        if r.entity_type in ('DATE_TIME', 'DATE'):
            if S._filter_dates(content, [r]):
                kept.append(r)
        else:
            state = {'excerpt': _build_context(content, r.start, r.end, 90)}
            ans = _so_post(state, {'is_phi': {
                'type': 'noul', 'instructions': IS_PHI_QUESTION}})
            p = _so_noul(ans, 'is_phi')
            if verbose:
                print(f'    [P2 {r.entity_type:16s} '
                      f'{content[r.start:r.end]!r:26s} p={p:.2f} '
                      f'-> {"DEID" if p >= PHI_THRESHOLD else "keep"}]')
            if p >= PHI_THRESHOLD:
                kept.append(r)
    return kept


def run_doc(name, content, config, precision, shift, use_cache, verbose=False):
    cands = gen_candidates(content, config, use_cache)
    kept = apply_precision(content, cands, precision, verbose)
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
    ap.add_argument('--config', required=True, help='R1|R2|R3, +gemma, +openmed')
    ap.add_argument('--precision', required=True, choices=['P1', 'P2'])
    ap.add_argument('--only', default=None, help='substring filter on note name')
    ap.add_argument('--out', default=None, help='write JSON result file')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--no-cache', action='store_true')
    args = ap.parse_args()

    shift = 15  # fixed; scoring only checks whether a date string changed
    rows, agg = [], [0, 0, 0]
    t_all = time.monotonic()
    for name, content, ext in DOCS:
        if args.only and args.only not in name:
            continue
        t0 = time.monotonic()
        out = run_doc(name, content, args.config, args.precision, shift,
                      not args.no_cache, args.verbose)
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
```

- [ ] **Step 3: Smoke-test on the synthetic notes (no Ollama needed)**

Run:

```
venv/bin/python scripts/pipeline_test.py --config R3 --precision P1 --only AB-SYNTH --no-cache
```

Expected: 3 synthetic notes each print a `leaks/lost/unshifted/time` line plus the `== R3 P1 ==` aggregate line; no traceback. (R3 = spaCy+Stanford+rules; P1 = production filter; no LLM/nimble, so this is fast.)

- [ ] **Step 4: Validate the harness against the known Approach-A numbers**

Run:

```
venv/bin/python scripts/pipeline_test.py --config R3 --precision P1 --out scripts/results_stage0.json
```

Expected: the aggregate `leaks/lost/unshifted` for `R3 P1` matches the previously recorded **Approach A** result (`leaks=4, lost=4, unshifted=1` — see the final comparison table in the spec). If it does not match, STOP and debug the harness (most likely a candidate-gen or precision wiring bug) before proceeding. Do not proceed to Task 4 until `R3 P1` reproduces Approach A exactly.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_test.py .gitignore scripts/results_stage0.json
git commit -m "test(deid): staged comparison harness (recall x precision, T0 dates)"
```

---

### Task 4: Stage 1 — traditional NER (`R1` vs `R2` vs `R3`, held `P1 + T0`)

Pick the best traditional base. All three are pure in-process NER (no Ollama), so run them **in parallel** on the 12 cores. `R3` candidates are already cached from Task 3 Step 4, so `R3` is instant; `R1`/`R2` compute fresh.

**Files:** none (run-only). Writes `scripts/results_s1_{R1,R2,R3}.json`.

- [ ] **Step 1: Launch all three in parallel**

```bash
( venv/bin/python scripts/pipeline_test.py --config R1 --precision P1 --out scripts/results_s1_R1.json ) &
( venv/bin/python scripts/pipeline_test.py --config R2 --precision P1 --out scripts/results_s1_R2.json ) &
( venv/bin/python scripts/pipeline_test.py --config R3 --precision P1 --out scripts/results_s1_R3.json ) &
wait
```

Expected: each prints per-note lines + a `== Rn P1 ==` aggregate line. (If a process dies on memory, re-run the failed one alone — 3 simultaneous model loads fit in 34 GB, but if not, run two at a time.)

- [ ] **Step 2: Record the three aggregates and pick winner `W`**

From the three `== ... ==` lines, write them into the `## Results → Stage 1` table below. **Winner W** = lowest `(leaks, lost, unshifted)`. Record the choice and a one-line reason.

- [ ] **Step 3: Commit the stage-1 result JSONs**

```bash
git add scripts/results_s1_*.json
git commit -m "test(deid): stage 1 results (R1/R2/R3, P1+T0); W=<_FILL_>"
```

---

### Task 5: Stage 2 — add LLM to W (`W`, `W+gemma`, `W+OpenMed`, held `P1 + T0`)

`W` is instant (cached). `W+gemma` is Ollama-bound (\~40 s/note); `W+OpenMed` is in-process CPU (\~8.5 s/note). They use different primary resources, so run the two LLM variants **in parallel** after the instant `W`.

**Files:** none (run-only). Writes `scripts/results_s2_{W,Wgemma,Wopenmed}.json` (replace `W` with the Stage-1 winner, e.g. `R3`).

- [ ] **Step 1: Run the instant base, then the two LLM variants in parallel**

```bash
venv/bin/python scripts/pipeline_test.py --config [[ORCA_RICH_MD:c860d15941e18d8de5224decd53f1a44:inline-html:%3CW%3E]] --precision P1 --out scripts/results_s2_[[ORCA_RICH_MD:c860d15941e18d8de5224decd53f1a44:inline-html:%3CW%3E]].json
( venv/bin/python scripts/pipeline_test.py --config [[ORCA_RICH_MD:c860d15941e18d8de5224decd53f1a44:inline-html:%3CW%3E]]+gemma --precision P1 --out scripts/results_s2_[[ORCA_RICH_MD:c860d15941e18d8de5224decd53f1a44:inline-html:%3CW%3E]]gemma.json ) &
( venv/bin/python scripts/pipeline_test.py --config [[ORCA_RICH_MD:c860d15941e18d8de5224decd53f1a44:inline-html:%3CW%3E]]+openmed --precision P1 --out scripts/results_s2_[[ORCA_RICH_MD:c860d15941e18d8de5224decd53f1a44:inline-html:%3CW%3E]]openmed.json ) &
wait
```

Replace every `<W>` with the Stage-1 winner (e.g. `R3`). Expected: three aggregate lines. (If the two LLM jobs contend for CPU and either OOMs or times out, re-run them one at a time — the cache keeps candidates, so a re-run only re-scores.)

- [ ] **Step 2: Record aggregates and pick the best recall config**

Write the three aggregates into the `## Results → Stage 2` table. **Best recall** = lowest `(leaks, lost, unshifted)` among `W`, `W+gemma`, `W+OpenMed`. If `+gemma`/`+OpenMed` do not beat `W`, record that and keep `W`. Record the chosen config (call it **R\***).

- [ ] **Step 3: Commit**

```bash
git add scripts/results_s2_*.json
git commit -m "test(deid): stage 2 results (LLM additions to W); R*=<_FILL_>"
```

---

### Task 6: Stage 3 — precision (`P1` vs `P2`) on R\*, held `T0`

Same candidate set (R\* cached from Stage 2), only the precision mechanism varies. `P1` is instant; `P2` is nimble-bound (\~15 s per non-date candidate). Run **in parallel**.

**Files:** none (run-only). Writes `scripts/results_s3_{P1,P2}.json`.

- [ ] **Step 1: Run both in parallel**

```bash
( venv/bin/python scripts/pipeline_test.py --config <R*> --precision P1 --out scripts/results_s3_P1.json ) &
( venv/bin/python scripts/pipeline_test.py --config <R*> --precision P2 --out scripts/results_s3_P2.json ) &
wait
```

Replace `<R*>` with the Stage-2 winner. Expected: two aggregate lines. `P2` is the slow one (nimble per non-date span); watch the `[P2 ...]` verbose lines if you add `--verbose` to spot mis-judged clinical terms.

- [ ] **Step 2: Record aggregates and pick the best precision**

Write the two aggregates into the `## Results → Stage 3` table. **Best precision** = lowest `(leaks, lost, unshifted)` among `P1`, `P2` (call it **P\***).

- [ ] **Step 3: Commit**

```bash
git add scripts/results_s3_*.json
git commit -m "test(deid): stage 3 results (P1 vs P2 on R*); P*=<_FILL_>"
```

---

### Task 7: Stage 5 — assemble and document the final recommendation

Run the assembled pipeline `R* + P* + T0` once more end-to-end (fresh, `--no-cache`, to confirm the cached numbers hold), confirm it matches the Stage-3 numbers, and fill in the final recommendation.

**Files:** Modify `docs/superpowers/plans/2026-10-17-deid-pipeline-test.md` (the `## Results` section). Writes `scripts/results_final.json`.

- [ ] **Step 1: Final confirmation run**

```bash
venv/bin/python scripts/pipeline_test.py --config <R*> --precision <P*> --no-cache --out scripts/results_final.json --verbose
```

Expected: aggregate matches the Stage-3 `P*` line (same config → same spans → same numbers, modulo scoring determinism). If it differs, note why.

- [ ] **Step 2: Fill in the `## Results` section and the recommendation**

Complete every `<!-- FILL -->` in the `## Results` section with the recorded numbers, and write the final recommendation in the `### Recommendation` subsection: the chosen `(R*, P*)`, its `(leaks, lost, unshifted)`, the trade-offs vs the alternatives, and whether it should replace the shipped default (R3 + P1 + T0).

- [ ] **Step 3: Commit**

```bash
git add scripts/results_final.json docs/superpowers/plans/2026-10-17-deid-pipeline-test.md
git commit -m "test(deid): stage 5 final result + documented recommendation"
```

---

## Results

> Filled in as each stage completes. Aggregates are summed over all 14 notes. Lower is better on every column. `time` is wall-clock for the config (recorded, NOT a ranking criterion — latency is out of scope).

### Stage 1 — traditional NER (P1 + T0)


| Config                    | leaks         | lost          | unshifted     | time          | note |
| ------------------------- | ------------- | ------------- | ------------- | ------------- | ---- |
| R1 (spaCy+rules)          | 12            | 3             | 7             | 18s           | general NER: more PII + dates leak |
| R2 (Stanford+rules)       | 4             | 1             | 1             | 28s           | clinical NER: precise |
| R3 (spaCy+Stanford+rules) | 4             | 4             | 1             | cached        | shipped default; spaCy adds noise |


**Winner W:** R2 (Stanford + rules) — reason: ties R3 on leaks (4) and unshifted (1) but far better precision (lost=1 vs 4). Stanford's clinical NER matches the union's PII recall while flagging far fewer false clinical terms; spaCy adds noise (lost) without adding recall. R1 (spaCy alone) is clearly worst (leaks=12, unshifted=7).

### Stage 2 — LLM additions to W (P1 + T0)


| Config      | leaks         | lost          | unshifted     | time          | note |
| ----------- | ------------- | ------------- | ------------- | ------------- | ---- |
| W           | 4             | 1             | 1             | cached        | Stanford+rules baseline |
| W + gemma   | 1             | 1             | 1             | 394s          | recovers 3 Stanford-missed locations |
| W + OpenMed | 2             | 1             | 1             | 120s          | recovers Mahishadal only |


**Best recall R\*:** R2+gemma — reason: leaks=1 (only the name variant 'Dey'; unshifted=1 is the bare-year '2023' artifact). gemma recovers the 3 locations (Mahishadal, West Medinipur, Sitapur) that Stanford and OpenMed both miss, at zero cost to precision (lost=1) or dates (unshifted=1). OpenMed recovers only 1 of the 3 (leaks=2).

### Stage 3 — precision on R\* (T0)


| Config                 | leaks         | lost          | unshifted     | time          | note |
| ---------------------- | ------------- | ------------- | ------------- | ------------- | ---- |
| P1 (production filter) | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> |      |
| P2 (nimble judge)      | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> |      |


**Best precision P\*:** <!-- FILL --> — reason: <!-- FILL -->

### Stage 5 — assembled (R\* + P\* + T0)


| Config    | leaks         | lost          | unshifted     | time          | note               |
| --------- | ------------- | ------------- | ------------- | ------------- | ------------------ |
| R\* + P\* | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> | <!-- FILL --> | vs shipped default |


### Recommendation

<!-- FILL: the recommended (R*, P*), its (leaks, lost, unshifted), the trade-offs vs the alternatives (recall vs clinical precision vs dates), and whether to replace the shipped default R3+P1+T0. Note any gemma-specific issues (name+age span merging, short-date interference) if gemma is in the winner. -->