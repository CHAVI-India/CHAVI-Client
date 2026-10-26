"""Text deidentification service for the extractor pipeline.

Runs after file processing/OCR and before extraction: produces a new
versioned ProcessedText whose content has PHI replaced by numbered generic
tags (<PERSON_1>, <IN_AADHAAR_1>, ...) and all dates shifted by a random
per-document offset stored (encrypted) on the row. save_extraction_results
subtracts that offset from extracted date fields so real dates are written
back.

The analyzer is built extractor-locally (spaCy + optional
HuggingFaceNerRecognizer + shared Indian recognizer bundle from
deidentification.utils.indian_id_recognizers) plus text-specific
recognizers from deid_recognizers.py. No deidentification-app models are
touched.
"""

import csv
import io
import logging
import random
import re
from pathlib import Path

from datetime import datetime
from django.conf import settings
from django.utils import timezone
from presidio_analyzer import AnalyzerEngine, LemmaContextAwareEnhancer

from extractor.services.deid_recognizers import (
    build_patient_recognizers,
    build_text_recognizers,
)
from extractor.services import deid_rules
from extractor.services.embeddings import _resolve_device
from extractor.services.llm_ner import LlmNerRecognizer
from extractor.services.url_policy import is_cloud_provider, is_local_endpoint

logger = logging.getLogger(__name__)

TAG_RE = re.compile(r'<[A-Z_]+(_\d+)?>')

# Every entity type the deid pipeline can emit, for the review-page
# redact-type dropdown. Union of: Presidio default recognizers, the HF NER
# label map (DEID_HF_LABEL_MAP), the Indian ID recognizers, and the custom
# text recognizers (deid_recognizers.build_text_recognizers). MANUAL is a
# catch-all for redactions that don't fit a specific type. Keep in sync with
# the recognizers above; the review view also appends any type already
# present in a document so legacy/manual tags stay selectable.
PHI_ENTITY_TYPES = [
    'PERSON', 'ORGANIZATION', 'LOCATION', 'DATE_TIME', 'PHONE_NUMBER',
    'EMAIL_ADDRESS', 'MEDICAL_RECORD_NUMBER', 'PATIENT_ID',
    'IN_AADHAAR', 'IN_PAN', 'IN_ABHA', 'IN_UPI', 'IN_PINCODE',
    'IN_DRIVING_LICENSE', 'IN_RELIGION',
    'URL', 'IP_ADDRESS', 'CREDIT_CARD', 'PASSPORT_NUMBER',
    'MANUAL',
]
# Friendly dropdown labels; types not listed here use their own name.
PHI_ENTITY_LABELS = {
    'DATE_TIME': 'DATE',
    'MEDICAL_RECORD_NUMBER': 'MRN',
    'MANUAL': 'Manual (other)',
}


class LlmDeidConfigurationError(ValueError):
    """LLM deid engine requested but no usable local configuration exists."""

# Month-name tokens -> month number. Full and common abbreviated spellings,
# case-insensitive — strptime's %b would miss variants like 'Sept' or
# 'MARCH', so month names are resolved to numbers before parsing.
_MONTH_NAMES = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11,
    'dec': 12,
}

# Trailing time-of-day (e.g. ' 14:30', ' 02:30:10', ' 2:30 pm'). Preserved
# verbatim; only the date part is shifted.
_TIME_SUFFIX_RE = re.compile(
    r'\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp]\.?[Mm]\.?)?$')
# Three numeric tokens with a consistent separator: '2024-03-15',
# '15/03/2024', '15.03.24', '25-01-05', ...
_NUMERIC_DATE_RE = re.compile(r'^(\d{1,4})([/.-])(\d{1,2})\2(\d{1,4})$')
# <day> <Month> <year> — '15 March 2024', '15th Mar 24'.
_DAY_MONTH_YEAR_RE = re.compile(
    r'^(\d{1,2})(st|nd|rd|th)?\s+([A-Za-z]{3,9})\s+(\d{4}|\d{2})$')
# <Month> <day>,? <year> — 'March 15, 2024', 'Mar 15 24'.
_MONTH_DAY_YEAR_RE = re.compile(
    r'^([A-Za-z]{3,9})(,)?\s+(\d{1,2})(,)?\s+(\d{4}|\d{2})$')
# <Month> <year> — 'March 2024', 'Mar 24'.
_MONTH_YEAR_RE = re.compile(r'^([A-Za-z]{3,9})\s+(\d{4}|\d{2})$')


def _month_number(token: str):
    """Month number for a name token ('Mar', 'MARCH', 'sept', ...); None when
    the token is not a recognised month name."""
    t = token.lower()
    if t in _MONTH_NAMES:
        return _MONTH_NAMES[t]
    if len(t) >= 3:
        for name, num in _MONTH_NAMES.items():
            if t.startswith(name):
                return num
    return None


_MONTH_FULL = [
    '', 'January', 'February', 'March', 'April', 'May', 'June', 'July',
    'August', 'September', 'October', 'November', 'December']
_MONTH_ABBR = [
    '', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep',
    'Oct', 'Nov', 'Dec']


def _month_token_for(month_num: int, original: str) -> str:
    """Month name for `month_num`, keeping the original token's style
    (abbreviated vs full, case). The original token is kept verbatim when
    the month is unchanged so the surface format is preserved exactly."""
    if _month_number(original) == month_num:
        return original
    names = _MONTH_ABBR if len(original) == 3 else _MONTH_FULL
    tok = names[month_num]
    if original.islower():
        return tok.lower()
    if original.isupper():
        return tok.upper()
    return tok


def _two_digit_year(year: int) -> int:
    """Same convention as strptime('%y'): 0-68 -> 2000s, 69-99 -> 1900s."""
    return 2000 + year if year <= 68 else 1900 + year


def _ordinal_suffix(day: int) -> str:
    if 11 <= day % 100 <= 13:
        return 'th'
    return {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')


def _parse_date_surface(s):
    """Parse a bare date surface into (datetime, emit), where emit re-formats
    any datetime in the same surface format. (None, None) when unparseable.

    Explicit per-shape parsing instead of dayfirst/yearfirst heuristics —
    parse and re-emit use one shape, so the round trip is exact. Day-first
    is the convention for ambiguous all-numeric dates (DD/MM).
    """
    m = _NUMERIC_DATE_RE.match(s)
    if m:
        a, sep, _b, c = m.groups()
        fallback = None
        if len(a) >= 4:
            fmt = f'%Y{sep}%m{sep}%d'
        elif len(c) >= 4:
            fmt = f'%d{sep}%m{sep}%Y'
        else:
            # Both years are short: day-first, year-first as fallback.
            fmt = f'%d{sep}%m{sep}%y'
            fallback = f'%y{sep}%m{sep}%d'
        try:
            parsed = datetime.strptime(s, fmt)
        except ValueError:
            if fallback is None:
                return None, None
            try:
                parsed = datetime.strptime(s, fallback)
            except ValueError:
                return None, None
            fmt = fallback
        return parsed, lambda dt, fmt=fmt: dt.strftime(fmt)

    m = _DAY_MONTH_YEAR_RE.match(s)
    if m:
        day, ord_suffix, month_tok, year = m.groups()
        month = _month_number(month_tok)
        if month is None:
            return None, None
        try:
            parsed = datetime(
                _two_digit_year(int(year)) if len(year) == 2 else int(year),
                month, int(day))
        except ValueError:
            return None, None
        two_digit = len(year) == 2

        def emit_day_month_year(dt, month_tok=month_tok, two_digit=two_digit,
                                had_ordinal=ord_suffix is not None):
            d = f'{dt.day:02d}' + (
                _ordinal_suffix(dt.day) if had_ordinal else '')
            y = f'{dt.year % 100:02d}' if two_digit else f'{dt.year:04d}'
            return (f'{d} {_month_token_for(dt.month, month_tok)} {y}')

        return parsed, emit_day_month_year

    m = _MONTH_DAY_YEAR_RE.match(s)
    if m:
        month_tok, comma1, day, comma2, year = m.groups()
        month = _month_number(month_tok)
        if month is None:
            return None, None
        try:
            parsed = datetime(
                _two_digit_year(int(year)) if len(year) == 2 else int(year),
                month, int(day))
        except ValueError:
            return None, None
        two_digit = len(year) == 2

        def emit_month_day_year(dt, month_tok=month_tok, two_digit=two_digit,
                                c1=comma1, c2=comma2):
            y = f'{dt.year % 100:02d}' if two_digit else f'{dt.year:04d}'
            return (f'{_month_token_for(dt.month, month_tok)}{c1 or ""} '
                    f'{dt.day:02d}{c2 or ""} {y}')

        return parsed, emit_month_day_year

    m = _MONTH_YEAR_RE.match(s)
    if m:
        month_tok, year = m.groups()
        month = _month_number(month_tok)
        if month is None:
            return None, None
        try:
            parsed = datetime(
                _two_digit_year(int(year)) if len(year) == 2 else int(year),
                month, 1)
        except ValueError:
            return None, None
        two_digit = len(year) == 2

        def emit_month_year(dt, month_tok=month_tok, two_digit=two_digit):
            y = f'{dt.year % 100:02d}' if two_digit else f'{dt.year:04d}'
            return f'{_month_token_for(dt.month, month_tok)} {y}'

        return parsed, emit_month_year

    return None, None


def _shifted_date_text(surface: str, shift_days: int) -> str:
    """Shift a date surface by shift_days, preserving its surface format.

    Supports the shapes the recognizers emit: numeric dates in any
    day/month/year order with /, - or . separators and 2- or 4-digit years,
    month names in either order (optional comma/ordinal), month-only dates,
    and an optional trailing time-of-day which is preserved verbatim.
    Unparseable surfaces become <DATE>.
    """
    stripped = surface.strip()
    time_match = _TIME_SUFFIX_RE.search(stripped)
    time_part = ''
    date_part = stripped
    if time_match:
        (date_part, time_part) = (
            stripped[:time_match.start()], stripped[time_match.start():])
    parsed, emit = _parse_date_surface(date_part)
    if parsed is None:
        return '<DATE>'
    return emit(parsed + timezone.timedelta(days=shift_days)) + time_part


def _normalize_tag_key(text: str) -> str:
    return ' '.join(text.split()).lower()


class TextDeidentificationService:
    _analyzer = None       # lazy per-process singleton
    _engine_mode = None    # 'full' | 'degraded'
    _llm_analyzer = None   # lazy singleton without HF NER (rules only)

    @classmethod
    def _resolve_pipeline(cls, pipeline, backend, client_config_id):
        """Resolve (pipeline, openmed) for a run. `openmed` is 'openmed' or
        None. `pipeline` (a TextDeidentificationPipelineConfig) wins when
        given; otherwise `backend` is resolved: 'default' -> the default
        pipeline, 'presidio'/'llm' -> legacy equivalents, 'openmed' -> the
        legacy OpenMed path.
        """
        from extractor.models import ClientConfiguration, \
            TextDeidentificationPipelineConfig as P

        if pipeline is not None:
            return pipeline, None
        backend = (backend or 'default')
        if backend == 'openmed':
            return None, 'openmed'
        if backend in ('', 'default'):
            default = P.objects.filter(is_default=True).first()
            if default is None:
                raise LlmDeidConfigurationError(
                    'No default deidentification pipeline is configured.')
            return default, None
        if backend == 'presidio':
            return P(ner_engine='hf', hf_model_id=settings.DEID_HF_NER_MODEL,
                     hf_label_map=settings.DEID_HF_LABEL_MAP,
                     hf_threshold=settings.DEID_HF_NER_THRESHOLD,
                     min_confidence=getattr(
                         settings, 'EXTRACTOR_DEID_SCORE_THRESHOLD', 0.35)), None
        if backend == 'llm':
            cfg = ClientConfiguration.objects.filter(id=client_config_id).first()
            if cfg is None:
                raise LlmDeidConfigurationError(
                    'No configuration for the llm backend.')
            return P(ner_engine='spacy', system2_model=cfg,
                     min_confidence=getattr(
                         settings, 'EXTRACTOR_DEID_SCORE_THRESHOLD', 0.35)), None
        raise LlmDeidConfigurationError(f"Unknown deid backend {backend!r}.")

    @classmethod
    def _get_analyzer(cls):
        if cls._analyzer is None:
            cls._analyzer, cls._engine_mode = cls._build_analyzer()
        return cls._analyzer, cls._engine_mode

    @classmethod
    def _get_llm_analyzer(cls):
        """Rules + spaCy NER analyzer without the HF/Stanford NER — a
        replacement NER (LLM or OpenMed) is supplied per run as an
        ad-hoc recognizer and runs alongside spaCy NER (union: the
        replacement model improves recall, spaCy catches what it
        misses). Precision is handled by _filter_results' clinical
        allowlist, which drops general-domain false positives
        ('Nottingham', 'Grade III', 'mammogram') on every engine.
        """
        if cls._llm_analyzer is None:
            cls._llm_analyzer, _ = cls._build_analyzer(include_hf_ner=False)
        return cls._llm_analyzer

    @classmethod
    def _build_analyzer(cls, include_hf_ner=None, slim_ner=False):
        nlp_engine = None
        if slim_ner:
            from presidio_analyzer.nlp_engine import SlimSpacyNlpEngine
            nlp_engine = SlimSpacyNlpEngine(supported_languages=['en'])
        analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine,
            supported_languages=["en"],
            context_aware_enhancer=LemmaContextAwareEnhancer(
                context_similarity_factor=0.35,
                min_score_with_context_similarity=0.4,
            ),
        )
        engine_mode = 'degraded'

        if include_hf_ner is None:
            backend = getattr(settings, 'EXTRACTOR_DEID_NER_BACKEND', 'hf')
        else:
            backend = 'hf' if include_hf_ner else 'none'
        if backend == 'hf':
            try:
                from presidio_analyzer.predefined_recognizers.ner import (
                    HuggingFaceNerRecognizer,
                )

                # __init__ -> load(): downloads/loads the HF model here
                recognizer = HuggingFaceNerRecognizer(
                    model_name=settings.DEID_HF_NER_MODEL,
                    label_mapping=settings.DEID_HF_LABEL_MAP,
                    threshold=settings.DEID_HF_NER_THRESHOLD,
                    aggregation_strategy="simple",
                    device=_resolve_device(),
                    supported_language="en",
                )
            except Exception as e:
                logger.warning(
                    f"HF NER model failed to load ({e}) — "
                    "text deid continuing with spaCy-only analyzer"
                )
            else:
                analyzer.registry.add_recognizer(recognizer)
                engine_mode = 'full'
        elif backend != 'none':
            logger.warning(
                f"Unknown EXTRACTOR_DEID_NER_BACKEND={backend!r} — "
                "spaCy-only analyzer"
            )

        if getattr(settings, 'DEID_LENIENT_INDIAN_IDS', True):
            from deidentification.utils.indian_id_recognizers import (
                build_indian_id_recognizers,
            )
            for recognizer in build_indian_id_recognizers():
                analyzer.registry.add_recognizer(recognizer)

        for recognizer in build_text_recognizers():
            analyzer.registry.add_recognizer(recognizer)

        return analyzer, engine_mode

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    @classmethod
    def deidentify(cls, processed_text, user=None, pipeline=None,
                   backend='default', client_config_id=None):
        """Produce a deidentified version of a ProcessedText row.

        `pipeline` (a TextDeidentificationPipelineConfig) selects the
        pipeline; when None, `backend` is resolved (default -> the default
        pipeline, 'presidio'/'llm' -> legacy equivalents, 'openmed' -> the
        legacy OpenMed path). Returns the new ProcessedText row, or None
        when skipped.
        """
        from extractor.models import ProcessedText
        from extractor.services.file_processor import FileProcessorService

        if processed_text.deidentified:
            return None

        pipeline, openmed = cls._resolve_pipeline(
            pipeline, backend, client_config_id)
        content = FileProcessorService.get_processed_content(processed_text)
        if not content:
            raise ValueError("Cannot read source processed text content")

        date_range = (pipeline.extractor_date_shift_range
                      if (pipeline is not None
                          and pipeline.extractor_date_shift_range is not None)
                      else getattr(settings, 'EXTRACTOR_DEID_DATE_SHIFT_RANGE',
                                   90))
        shift = random.randint(-date_range, date_range)

        patient = processed_text.file_upload.patient_id
        path = str(processed_text.processed_file_path or '')

        if openmed:
            # legacy OpenMed path (unchanged behaviour)
            from extractor.services.openmed_ner import OpenMedNerRecognizer
            ner_recognizer = OpenMedNerRecognizer()
            engine_mode = 'openmed'
            deid_model = getattr(
                settings, 'EXTRACTOR_DEID_OPENMED_MODEL',
                'pii_superclinical_large')
            s2_cfg = None
            if path.endswith('.csv'):
                new_content, entities, columns, repl = cls._deidentify_csv(
                    content, shift, patient, ner_recognizer)
            else:
                new_content, entities, repl = cls._deidentify_text(
                    content, shift, patient, ner_recognizer)
                columns = []
            deid_pipeline_row = None
        else:
            if path.endswith('.csv'):
                new_content, entities, columns, repl = cls._deidentify_csv_for(
                    content, shift, patient, pipeline)
            else:
                new_content, entities, repl = cls._deidentify_text_for(
                    content, shift, patient, pipeline)
                columns = []
            engine_mode = pipeline.ner_engine
            deid_model = (pipeline.hf_model_id if pipeline.ner_engine == 'hf'
                          else (pipeline.system2_model.llm_model_name
                                if pipeline.system2_model_id else ''))
            s2_cfg = pipeline.system2_model if pipeline.system2_model_id else None
            deid_pipeline_row = pipeline if pipeline.pk else None

        # Aggregate identical (tag, original) pairs into the review map.
        deid_map = {}
        for e in repl:
            key = (e['tag'], e['original'])
            if key in deid_map:
                deid_map[key]['count'] += 1
            else:
                deid_map[key] = {
                    'tag': e['tag'], 'type': e['type'],
                    'original': e['original'], 'count': 1}

        file_upload = processed_text.file_upload
        version = FileProcessorService._next_version(file_upload)
        new_path = cls._output_path(file_upload, version, path or '.txt')
        cls._write_output(new_path, new_content)

        return ProcessedText.objects.create(
            file_upload=file_upload,
            processed_file_path=new_path,
            source_sheet=processed_text.source_sheet,
            content_length=len(new_content),
            version=version,
            processed_by_user=user,
            deidentified=True,
            deidentified_source=processed_text,
            deid_engine=engine_mode,
            deid_model=deid_model,
            deid_entities=entities,
            deid_csv_columns_flagged=columns,
            deid_map=list(deid_map.values()),
            deid_date_shift_days=shift,
            deid_client_config=s2_cfg,
            deid_pipeline=deid_pipeline_row,
        )

    @classmethod
    def deidentify_if_needed(cls, processed_text, user=None, backend='default',
                             client_config_id=None):
        """Dispatch-safe wrapper: skip when deid output already exists."""
        if not getattr(settings, 'EXTRACTOR_DEID_ENABLED', True):
            return None
        if processed_text.deid_derivatives.exists():
            return processed_text.deid_derivatives.order_by('-version').first()
        return cls.deidentify(
            processed_text, user=user, backend=backend,
            client_config_id=client_config_id)

    @classmethod
    def save_manual_edit(cls, processed_text, new_content, user=None):
        """Persist a review-page edit to the deidentified version file."""
        file_path = processed_text.resolve_path()
        if not file_path or not file_path.exists():
            raise ValueError("Processed text has no file to edit")
        file_path.write_text(new_content, encoding='utf-8')
        processed_text.content_length = len(new_content)
        processed_text.deid_manual_edits += 1
        processed_text.save(
            update_fields=['content_length', 'deid_manual_edits'])

    @classmethod
    def mark_reviewed(cls, processed_text, user=None):
        processed_text.deid_reviewed = True
        processed_text.deid_reviewed_by = user
        processed_text.deid_reviewed_at = timezone.now()
        processed_text.save(update_fields=[
            'deid_reviewed', 'deid_reviewed_by', 'deid_reviewed_at'])

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    @classmethod
    def restore_tag(cls, processed_text, tag):
        """Undo a deidentification: replace every occurrence of `tag` with
        its recorded original surface and drop the map entries. Returns the
        number of restored replacements (0 when the tag is unknown)."""
        from extractor.services.file_processor import FileProcessorService

        entries = [e for e in (processed_text.deid_map or [])
                   if e.get('tag') == tag]
        if not entries:
            return 0
        content = FileProcessorService.get_processed_content(processed_text)
        original = entries[0]['original']
        count = content.count(tag)
        if not count:
            return 0
        new_content = content.replace(tag, original)
        processed_text.deid_map = [
            e for e in processed_text.deid_map if e.get('tag') != tag]
        cls.save_manual_edit(processed_text, new_content)
        processed_text.save(update_fields=['deid_map'])
        return count

    @classmethod
    def _deidentify_text(cls, content, shift, patient, ner_recognizer=None):
        if ner_recognizer is not None:
            analyzer = cls._get_llm_analyzer()
        else:
            analyzer, _ = cls._get_analyzer()
        ad_hoc = build_patient_recognizers(patient)
        if ner_recognizer is not None:
            ad_hoc = [ner_recognizer] + ad_hoc
        results = analyzer.analyze(
            text=content,
            language='en',
            score_threshold=getattr(
                settings, 'EXTRACTOR_DEID_SCORE_THRESHOLD', 0.35),
            ad_hoc_recognizers=ad_hoc,
        )
        results = cls._resolve_overlaps(cls._filter_results(content, results))
        repl = []
        new_content = cls._apply_replacements(
            content, results, shift, {}, repl)
        return new_content, cls._entity_counts(results), repl

    @classmethod
    def _deidentify_csv(cls, content, shift, patient, ner_recognizer=None):
        """Header-aware CSV pass: mapped columns are replaced wholesale;
        unmapped columns get per-cell NER with a shared tag map."""
        column_map = getattr(settings, 'EXTRACTOR_DEID_CSV_COLUMN_MAP', {})
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        if not rows:
            return cls._deidentify_text(
                content, shift, patient, ner_recognizer) + ([],)

        headers = rows[0]
        col_types = [column_map.get(h.strip().lower()) for h in headers]
        if not any(col_types):
            # No recognizable headers — treat the whole thing as text so
            # PHI in unmapped CSVs is still caught.
            new_content, counts, repl = cls._deidentify_text(
                content, shift, patient, ner_recognizer)
            return new_content, counts, [], repl

        if ner_recognizer is not None:
            analyzer = cls._get_llm_analyzer()
        else:
            analyzer, _ = cls._get_analyzer()
        ad_hoc = build_patient_recognizers(patient)
        if ner_recognizer is not None:
            ad_hoc = [ner_recognizer] + ad_hoc
        tag_map = {}
        all_results = []
        repl = []
        flagged = [
            headers[i] for i, t in enumerate(col_types) if t is not None]

        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(headers)
        for row in rows[1:]:
            for i, cell in enumerate(row):
                if not cell.strip() or i >= len(col_types):
                    continue
                col_type = col_types[i]
                if col_type == 'DATE_TIME':
                    shifted = _shifted_date_text(cell.strip(), shift)
                    repl.append({
                        'tag': shifted, 'type': 'DATE_TIME',
                        'original': cell.strip()})
                    row[i] = shifted
                    all_results.append(_FakeResult('DATE_TIME', cell))
                elif col_type is not None:
                    tag = cls._tag_for(col_type, cell, tag_map)
                    repl.append({
                        'tag': tag, 'type': col_type,
                        'original': cell.strip()})
                    row[i] = tag
                    all_results.append(_FakeResult(col_type, cell))
                else:
                    results = analyzer.analyze(
                        text=cell, language='en',
                        score_threshold=getattr(
                            settings, 'EXTRACTOR_DEID_SCORE_THRESHOLD', 0.35),
                        ad_hoc_recognizers=ad_hoc,
                    )
                    results = cls._resolve_overlaps(
                        cls._filter_results(cell, results))
                    row[i] = cls._apply_replacements(
                        cell, results, shift, tag_map, repl)
                    all_results.extend(
                        _FakeResult(r.entity_type, cell) for r in results)
            writer.writerow(row)

        return out.getvalue(), cls._entity_counts(all_results), flagged, repl

    _analyzer_cache = {}

    @classmethod
    def _build_analyzer_for(cls, pipeline):
        import os
        key = (pipeline.ner_engine,
               pipeline.hf_model_id if pipeline.ner_engine == 'hf' else None,
               pipeline.hf_threshold)
        if key in cls._analyzer_cache:
            return cls._analyzer_cache[key]
        nlp_engine = None
        if pipeline.ner_engine == 'hf':
            from presidio_analyzer.nlp_engine import SlimSpacyNlpEngine
            nlp_engine = SlimSpacyNlpEngine(supported_languages=['en'])
        analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine, supported_languages=['en'],
            context_aware_enhancer=LemmaContextAwareEnhancer(
                context_similarity_factor=0.35,
                min_score_with_context_similarity=0.4))
        if pipeline.ner_engine == 'hf':
            if pipeline.hf_token:
                os.environ['HF_TOKEN'] = pipeline.hf_token
            from presidio_analyzer.predefined_recognizers.ner import (
                HuggingFaceNerRecognizer)
            try:
                recognizer = HuggingFaceNerRecognizer(
                    model_name=pipeline.hf_model_id,
                    label_mapping=pipeline.hf_label_map,
                    threshold=pipeline.hf_threshold,
                    aggregation_strategy='simple', device=_resolve_device(),
                    supported_language='en')
                analyzer.registry.add_recognizer(recognizer)
            except Exception as e:
                logger.warning(f"HF NER {pipeline.hf_model_id} failed to load: {e}")
        if getattr(settings, 'DEID_LENIENT_INDIAN_IDS', True):
            from deidentification.utils.indian_id_recognizers import (
                build_indian_id_recognizers)
            for recognizer in build_indian_id_recognizers():
                analyzer.registry.add_recognizer(recognizer)
        for recognizer in build_text_recognizers():
            analyzer.registry.add_recognizer(recognizer)
        cls._analyzer_cache[key] = analyzer
        return analyzer

    @classmethod
    def _apply_precision(cls, text, results, pipeline):
        rules = pipeline.rules
        results = cls._filter_mechanical(text, results, rules)
        results = cls._filter_dates(text, results, rules)
        if pipeline.system_1_model_integration:
            results = cls._filter_system1(text, results, pipeline)
        else:
            results = cls._filter_clinical(text, results, rules)
        return results

    @classmethod
    def _filter_system1(cls, text, results, pipeline):
        from extractor.services import system1_judge
        kept = []
        for r in results:
            if r.entity_type in ('DATE_TIME', 'DATE'):
                kept.append(r)
                continue
            p = system1_judge.judge_span(
                pipeline.system_1_model, text, r.start, r.end,
                threshold=pipeline.system_1_threshold,
                window=pipeline.system_1_window)
            if p >= pipeline.system_1_threshold:
                kept.append(r)
        return kept

    @classmethod
    def _deidentify_text_for(cls, content, shift, patient, pipeline):
        analyzer = cls._build_analyzer_for(pipeline)
        ad_hoc = build_patient_recognizers(patient)
        if pipeline.system2_model_id:
            ad_hoc = [LlmNerRecognizer(pipeline.system2_model)] + ad_hoc
        results = analyzer.analyze(
            text=content, language='en',
            score_threshold=pipeline.min_confidence,
            ad_hoc_recognizers=ad_hoc)
        results = cls._apply_precision(content, results, pipeline)
        results = cls._resolve_overlaps(results)
        repl = []
        new_content = cls._apply_replacements(content, results, shift, {}, repl)
        return new_content, cls._entity_counts(results), repl

    @classmethod
    def _deidentify_csv_for(cls, content, shift, patient, pipeline):
        column_map = getattr(settings, 'EXTRACTOR_DEID_CSV_COLUMN_MAP', {})
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        if not rows:
            new_content, counts, repl = cls._deidentify_text_for(
                content, shift, patient, pipeline)
            return new_content, counts, [], repl
        headers = rows[0]
        col_types = [column_map.get(h.strip().lower()) for h in headers]
        if not any(col_types):
            new_content, counts, repl = cls._deidentify_text_for(
                content, shift, patient, pipeline)
            return new_content, counts, [], repl
        analyzer = cls._build_analyzer_for(pipeline)
        ad_hoc = build_patient_recognizers(patient)
        if pipeline.system2_model_id:
            ad_hoc = [LlmNerRecognizer(pipeline.system2_model)] + ad_hoc
        tag_map = {}
        all_results = []
        repl = []
        flagged = [headers[i] for i, t in enumerate(col_types) if t is not None]
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(headers)
        for row in rows[1:]:
            for i, cell in enumerate(row):
                if not cell.strip() or i >= len(col_types):
                    continue
                col_type = col_types[i]
                if col_type == 'DATE_TIME':
                    shifted = _shifted_date_text(cell.strip(), shift)
                    repl.append({'tag': shifted, 'type': 'DATE_TIME',
                                 'original': cell.strip()})
                    row[i] = shifted
                    all_results.append(_FakeResult('DATE_TIME', cell))
                elif col_type is not None:
                    tag = cls._tag_for(col_type, cell, tag_map)
                    repl.append({'tag': tag, 'type': col_type,
                                 'original': cell.strip()})
                    row[i] = tag
                    all_results.append(_FakeResult(col_type, cell))
                else:
                    results = analyzer.analyze(
                        text=cell, language='en',
                        score_threshold=pipeline.min_confidence,
                        ad_hoc_recognizers=ad_hoc)
                    results = cls._apply_precision(cell, results, pipeline)
                    results = cls._resolve_overlaps(results)
                    row[i] = cls._apply_replacements(
                        cell, results, shift, tag_map, repl)
                    all_results.extend(
                        _FakeResult(r.entity_type, cell) for r in results)
            writer.writerow(row)
        return out.getvalue(), cls._entity_counts(all_results), flagged, repl

    @staticmethod
    def _rules(rules):
        return rules if rules else deid_rules.default_rules()

    @staticmethod
    def _filter_mechanical(text, results, rules=None):
        """Mechanical drops: drop_types, empty surface, mid-word boundaries.

        Applies to every candidate type. Mid-word spans are HF tokenization
        artifacts (e.g. 'oph' of 'oropharynx') - real PHI spans align to word
        boundaries; spans often include surrounding spaces, so measure from
        the stripped surface edges. drop_types comes from the pipeline rules.
        """
        rules = TextDeidentificationService._rules(rules)
        drop_types = set(rules['drop_entity_types'])
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
    def _filter_dates(text, results, rules=None):
        """DATE_TIME drops: durations/ages/doses (rules['date_keep_patterns'])
        and the fraction counter. Real calendar dates survive to be shifted.

        Ages and clinical intervals ('1 month', '2 weeks', 'Age 56 years')
        are content, not identifiers - they are kept. Real dates shift.
        """
        rules = TextDeidentificationService._rules(rules)
        patterns = [re.compile(p, re.I) for p in rules['date_keep_patterns']]
        kept = []
        for r in results:
            surface = text[r.start:r.end].strip()
            if (r.entity_type == 'DATE_TIME'
                    and any(p.match(surface) for p in patterns)):
                continue
            if (r.entity_type == 'DATE_TIME'
                    and re.match(r'^\d{1,2}/\d{1,2}$', surface)
                    and re.search(r'fraction\s*$',
                                  text[max(0, r.start - 12):r.start], re.I)):
                continue
            kept.append(r)
        return kept

    @staticmethod
    def _filter_clinical(text, results, rules=None):
        """Clinical-precision drops: allowlist, clinical-prefix (PERSON/ORG),
        and short/lowercase/label LOCATION. Rules come from the pipeline."""
        rules = TextDeidentificationService._rules(rules)
        allowlist = {t.lower() for t in rules['clinical_allowlist']}
        prefix = re.compile(rules['clinical_prefix_pattern'], re.I)
        loc = rules['location']
        loc_pattern = re.compile(loc['pattern'])
        kept = []
        for r in results:
            surface = text[r.start:r.end].strip()
            if surface.lower() in allowlist:
                continue
            if r.entity_type in ('PERSON', 'ORGANIZATION') and prefix.match(surface):
                continue
            if r.entity_type == 'LOCATION':
                # Specimen/grid labels (A3, A5-A10), lowercase words and short
                # tokens are never real locations; genuine address tokens are
                # title-case or long digit runs and survive.
                if (len(surface) < loc['min_length']
                        or (loc.get('reject_lowercase') and surface.islower())
                        or loc_pattern.match(surface)):
                    continue
            kept.append(r)
        return kept

    @staticmethod
    def _filter_results(text, results, rules=None):
        """Drop recognizer hits that are implausible or unwanted for text.

        Composition of the three focused stages; a span is dropped iff any
        stage drops it. `rules` is the pipeline's rule bundle (None = defaults).
        """
        results = TextDeidentificationService._filter_mechanical(text, results, rules)
        results = TextDeidentificationService._filter_dates(text, results, rules)
        results = TextDeidentificationService._filter_clinical(text, results, rules)
        return results

    @staticmethod
    def _resolve_overlaps(results):
        """Keep highest-scoring span among overlaps; longest wins ties.

        A span that fully contains lower-scored overlaps wins regardless of
        score — e.g. the context-gated MRN pattern covering 'MR/24/012817'
        must beat the NER's two-letter 'MR' org tag, or the actual record
        digits leak while only the prefix is redacted.
        """
        if not results:
            return []
        ordered = sorted(
            results,
            key=lambda r: (-r.score, -(r.end - r.start), r.start))
        kept = []
        for r in ordered:
            overlapping = [k for k in kept
                           if r.start < k.end and r.end > k.start]
            if not overlapping:
                kept.append(r)
            elif all(r.start <= k.start and r.end >= k.end
                     for k in overlapping):
                kept = [k for k in kept if k not in overlapping] + [r]
        return sorted(kept, key=lambda r: r.start)

    @classmethod
    def _apply_replacements(cls, text, results, shift, tag_map,
                            replacements=None):
        """Splice replacements right-to-left; consistent numbered tags.

        Tags are assigned in document order (first occurrence = _1) before
        the right-to-left splice that keeps offsets valid. Every splice is
        recorded in `replacements` ({tag, type, original}) so the review UI
        can show and undo what each tag hid.
        """
        for r in sorted(results, key=lambda r: r.start):
            if r.entity_type != 'DATE_TIME':
                cls._tag_for(r.entity_type, text[r.start:r.end], tag_map)
        for r in sorted(results, key=lambda r: r.start, reverse=True):
            original = text[r.start:r.end]
            if r.entity_type == 'DATE_TIME':
                replacement = _shifted_date_text(original, shift)
            else:
                replacement = cls._tag_for(r.entity_type, original, tag_map)
            if replacements is not None:
                replacements.append({
                    'tag': replacement, 'type': r.entity_type,
                    'original': original})
            text = text[:r.start] + replacement + text[r.end:]
        return text

    @staticmethod
    def _tag_for(entity_type, original, tag_map):
        key = (entity_type, _normalize_tag_key(original))
        if entity_type == 'PATIENT_ID':
            return '<PATIENT_ID>'
        if key not in tag_map:
            count = sum(1 for (t, _) in tag_map if t == entity_type) + 1
            tag_map[key] = f'<{entity_type}_{count}>'
        return tag_map[key]

    @staticmethod
    def _entity_counts(results):
        counts = {}
        for r in results:
            counts[r.entity_type] = counts.get(r.entity_type, 0) + 1
        return counts

    @staticmethod
    def _output_path(file_upload, version, source_path):
        """processed/deid/<upload_id>/v<n>/<name>.deid.<ext>"""
        from extractor.services.file_processor import FileProcessorService
        output_dir = FileProcessorService._versioned_output_dir(
            'deid', file_upload, version)
        stem = Path(source_path).stem
        ext = Path(source_path).suffix or '.txt'
        return str(
            (output_dir / f'{stem}.deid{ext}')
            .relative_to(settings.MEDIA_ROOT))

    @staticmethod
    def _write_output(rel_path, content):
        abs_path = Path(settings.MEDIA_ROOT) / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding='utf-8')


class _FakeResult:
    """Minimal stand-in for RecognizerResult for CSV column replacements."""

    __slots__ = ('entity_type', 'start', 'end', 'score')

    def __init__(self, entity_type, surface):
        self.entity_type = entity_type
        self.start = 0
        self.end = len(surface)
        self.score = 1.0
