# PHI Redaction Strategy — `extractor`

All logic lives in `extractor/services/text_deidentification.py` and
`extractor/services/deid_recognizers.py`, with the shared India bundle in
`deidentification/utils/indian_id_recognizers.py`.

## Architecture

- **Pipeline position**: runs *after* file processing/OCR and *before*
  extraction. A Celery task (`deidentify_processed_text_task`) is
  auto-dispatched when a new `ProcessedText` version is created
  (`EXTRACTOR_DEID_AUTO_RUN`); extraction jobs are hard-blocked unless the
  source has `deidentified=True` and `deid_reviewed=True`
  (`EXTRACTOR_DEID_REQUIRE_REVIEW`).
- **Versioned output**: deid produces a *new* `ProcessedText` row
  (`deidentified_source` -> original) written to
  `processed/deid/<upload_id>/v<n>/<name>.deid.<ext>`. The original text is
  never mutated.
- **Analyzer**: a lazy per-process Presidio `AnalyzerEngine` singleton
  (`supported_languages=["en"]`) with `LemmaContextAwareEnhancer`
  (`context_similarity_factor=0.35`,
  `min_score_with_context_similarity=0.4`) — low-scoring patterns only fire
  when nearby context words corroborate them.
- **Engine modes**: `'full'` (HF NER loaded) vs `'degraded'` (spaCy + rules
  only, with a warning logged on HF load failure); controlled by
  `EXTRACTOR_DEID_NER_BACKEND` (`'hf'`/`'none'`). Mode and model are recorded
  on the row (`deid_engine`, `deid_model`).
- **Replacement scheme**:
  - Non-date PHI -> consistent numbered generic tags (`<PERSON_1>`,
    `<IN_AADHAAR_1>`, ...). Tags are assigned in document order, keyed by
    normalized surface so every occurrence of the same entity gets the same
    tag. `PATIENT_ID` always maps to unnumbered `<PATIENT_ID>`.
  - `DATE_TIME` -> **date shifting**, not tagging: a random per-document
    offset of +/- `EXTRACTOR_DEID_DATE_SHIFT_RANGE` (100 days) is applied
    while preserving the surface format (`_shifted_date_text`); unparseable
    surfaces degrade to `<DATE>`.
- **Reversibility**: the offset is stored on the row
  (`deid_date_shift_days`); `save_extraction_results` in
  `instructor_extractor.py` subtracts it from extracted date fields so
  *real* dates land in client_app. Unparseable extracted dates are flagged
  `unresolved` instead of storing the shifted value.
- **Audit/review**: every splice is recorded in `deid_map`
  (`{tag, type, original, count}`), powering a review UI with per-tag undo
  (`restore_tag`), manual edits (`save_manual_edit`), and sign-off
  (`mark_reviewed`).
- **CSV handling**: header-aware pass driven by
  `EXTRACTOR_DEID_CSV_COLUMN_MAP` — mapped columns (name, mrn, dob, phone,
  aadhaar, ...) are replaced wholesale with deterministic types; `DATE_TIME`
  columns are shifted; unmapped columns get per-cell NER sharing one
  `tag_map`. If no headers are recognized, the whole file falls back to the
  text path so PHI is still caught.

## Detection layers

Recognizer scores encode confidence: unambiguous formats score high
standalone (0.4-0.95); patterns that could false-positive on clinical
numerics start at **0.05** and depend on context words to cross the analyzer
floor (`EXTRACTOR_DEID_SCORE_THRESHOLD = 0.35`).

| Layer | Source | Covers |
|---|---|---|
| **1. spaCy NER** | Presidio default (`en_core_web_lg`) | PERSON, LOCATION, DATE_TIME, etc. |
| **2. HF NER** | `HuggingFaceNerRecognizer` — `StanfordAIMI/stanford-deidentifier-base`, threshold 0.20 (recall-favoring), CPU | clinical PHI spans via `DEID_HF_LABEL_MAP` |
| **3. Indian ID bundle** | `build_indian_id_recognizers()` (shared with pixel scrubbing, gated by `DEID_LENIENT_INDIAN_IDS`) | PAN, Voter ID, Passport, Vehicle Reg, GSTIN, Aadhaar (built-in w/ Verhoeff checksum **plus** lenient no-checksum variant for OCR-noisy digits), Indian mobile (`+91`/`0`/bare 10-digit) |
| **4. Text pattern recognizers** | `build_text_recognizers()` | `IN_ABHA` (14-digit + `@abdm`/`@sbx` handles), `IN_UPI` (context-gated), `IN_PINCODE` (context-gated), `IN_DRIVING_LICENSE`, `MEDICAL_RECORD_NUMBER` (prefixed segmented IDs at 0.95; looser MRN patterns at 0.05 + context), title-prefixed names (Dr./Smt./S/o...), `DATE_TIME` catch-alls for 4 date formats |
| **5. Gazetteer deny-lists** | `extractor/data/indian_names.txt` (332), `indian_locations.txt` (225), religion/caste list | `PERSON`, `LOCATION`, `IN_RELIGION` at 0.35-0.4 + context — compensates for spaCy's weak recall on Indian names/places |
| **6. Ad-hoc patient recognizers** | `build_patient_recognizers(patient)` | linked patient's `patient_id` (raw + canonical) -> `PATIENT_ID` @ 0.9; DOB in 6 format variants -> `DATE_TIME` @ 0.9 — guaranteed catch since uploads are already patient-linked |
| **7. CSV column map** | `EXTRACTOR_DEID_CSV_COLUMN_MAP` | deterministic per-column typing, no model needed |

## False-positive suppression

`_filter_results` drops implausible hits before replacement:

- **Entity-type blacklist** —
  `EXTRACTOR_DEID_DROP_ENTITY_TYPES = {'ID', 'AGE', 'NRP'}`: the HF model's
  catch-all `ID` label eats clinical numerics (measurements, lymph-node
  counts, markers like `p16`, `D2-40`); `AGE` isn't a direct identifier and
  ages are needed for extraction. Real identifiers are re-covered by the
  pattern recognizers.
- **Mid-word span rejection** — HF tokenization artifacts (e.g. `oph` of
  `oropharynx`, `ally` of `clinically`): any span whose stripped boundaries
  abut an alphanumeric character is dropped, since real PHI aligns to word
  boundaries.
- **DATE_TIME sanity** — bare digits/percentages (`^\d{1,3}%?$`) and
  explicit age surfaces (`56 Years`, `56-year-old`, `y/o`) are rejected.
- **LOCATION sanity** — drops spans <=3 chars, all-lowercase words
  (`anterior`, `trabeculae`), and specimen/grid labels (`A3`, `A5-A10`,
  `11-A14` via `^[A-Za-z]?-?\d[\w-]*$`); genuine address tokens (title-case
  names, PIN runs) survive.
- **Context gating by design** — noisy-but-necessary patterns (PIN code,
  UPI, loose MRN shapes) carry base score 0.05 and can only fire with
  corroborating context words.

## Overlap resolution

`_resolve_overlaps` runs after filtering:

1. Sort candidates by `(-score, -span_length, start)`.
2. Non-overlapping spans are kept greedily in that order — highest score
   wins.
3. **Containment override**: a span that fully contains all its overlapping
   rivals wins *regardless of score* — e.g. the context-gated MRN pattern
   covering `MR/24/012817` must beat NER's two-letter
   `MR -> ORGANIZATION` tag, otherwise only the prefix is redacted and the
   actual record digits leak.
4. Survivors are re-sorted by `start` for the replacement pass.

Replacement itself (`_apply_replacements`) pre-assigns all tags in document
order (so numbering is stable), then splices **right-to-left** so earlier
offsets stay valid.

**Design bias**: over-redaction is explicitly the safe direction
(`DEID_HF_NER_THRESHOLD` lowered for recall, lenient Aadhaar, gazetteer FPs
accepted) — the mandatory human review step is the backstop for mistakes in
both directions.
