"""Text deidentification service for the extractor pipeline.

Runs after file processing/OCR and before extraction: produces a new
versioned ProcessedText whose content has PHI replaced by numbered generic
tags (<PERSON_1>, <IN_AADHAAR_1>, ...) and every absolute date shifted by
a random per-document offset (one shift per document / CSV file) stored
(encrypted) on the row. save_extraction_results subtracts that offset from
extracted date fields so real dates are written back.

Date shifting happens BEFORE the deidentification flow begins (see
_shift_dates_pre_pass): every absolute date span is located (shape regexes
for the common surfaces, dateparser search_dates for the long tail),
parsed with dateparser, shifted by the per-document offset using date
arithmetic, and re-emitted in DD/MM/YYYY — a trailing time-of-day is
preserved verbatim ('27 Oct 26 14:30' -> '03/11/2026 14:30'). The shifted
date replaces the original in the text. Per policy NO component of the
pipeline redacts or re-writes dates: whatever the NER stage still labels
DATE_TIME (already-shifted spans, relative phrases, durations, label
words) is dropped, never replaced (see _drop_date_time_and_covered).

The analyzer is built extractor-locally (spaCy + optional
HuggingFaceNerRecognizer + shared Indian recognizer bundle from
deidentification.utils.indian_id_recognizers) plus text-specific
recognizers from deid_recognizers.py. No deidentification-app models are
touched.
"""

import logging
import random
import re
from pathlib import Path

from dateparser import parse as _dateparser_parse
from dateparser.data.languages_info import language_order as _DATEPARSER_LANGUAGES
from dateparser.search import search_dates as _search_dates_lib
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

# --- Date shifting ---------------------------------------------------------
# Dates get a single deterministic treatment, BEFORE the NER analyzer runs
# (one random shift per document / CSV file, drawn in `deidentify`):
#
# - Pass 1 (_shift_dates_pre_pass) locates every absolute date span — shape
#   regexes for the common surfaces, dateparser search_dates (ngram
#   strategy, strictly gated) for the long tail — parses each with
#   dateparser, shifts it by the per-document offset, and re-emits it in
#   DD/MM/YYYY with any trailing time-of-day preserved verbatim. The
#   shifted date replaces the original in the text.
#
# - The NER stage then never redacts or re-writes dates: whatever it still
#   labels DATE_TIME (already-shifted spans, relative phrases, durations,
#   label words like a bare 'Date') is dropped, never replaced
#   (_drop_date_time_and_covered). A mislabelled span of another type that
#   would swallow a shifted date is dropped too.
#
# Parsing is dateparser with PREFER_DAY_OF_MONTH='first' and
# PREFER_MONTH_OF_YEAR='first', so partial dates ('Oct 2026', '27 Oct')
# are deterministic — the 1st day, January — instead of anchoring to
# today. Every surface must carry an explicit date component (month name,
# 4-digit year, or a 3-token numeric date); durations ('3 days'), relative
# phrases ('next Tuesday') and bare times ('14:30') are rejected, because
# dateparser would resolve them against the current date.

# Month-name tokens -> month number. Full and common abbreviated spellings,
# case-insensitive — strptime's %b would miss variants like 'Sept' or
# 'MARCH', so month names are resolved to numbers before parsing.
_MONTH_NAMES = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
    'jul': 7, 'aug': 8, 'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11,
    'dec': 12,
}


def _month_number(token: str):
    """Month number for a name token ('Mar', 'MARCH', 'sept', ...); None
    when the token is not a recognised month name."""
    t = token.lower()
    if t in _MONTH_NAMES:
        return _MONTH_NAMES[t]
    if len(t) >= 3:
        for name, num in _MONTH_NAMES.items():
            if t.startswith(name):
                return num
    return None


# Trailing time-of-day (e.g. ' 14:30', ' 02:30:10', ' 2:30 pm',
# ', 14:59'). Preserved verbatim — including any separating comma — while
# only the date part is shifted.
_TIME_SUFFIX_RE = re.compile(
    r'[,;]?\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp]\.?[Mm]\.?)?$')

# Shape finders for locating candidate date spans inside a document
# (finditer). Each entry is (regex, group-index-of-the-month-name-token or
# None for fully numeric shapes). The regexes only CANDIDATE spans; the
# month token is validated against _MONTH_NAMES and the whole surface is
# parsed with _parse_date_span before a span is recorded — an invalid
# candidate must never swallow a real date in the leftmost-longest dedup.
#
#   <num><sep><num><sep><num>  — '2024-03-15', '15/03/2024', '15.03.24'
_NUMERIC_FIND_RE = re.compile(
    r'\b(\d{1,4})([/.-])(\d{1,2})\2(\d{1,4})\b')
# <day> <Month> <year> — '15 March 2024', '15th Mar 24', '16th of Sept 26'.
_DAY_MONTH_YEAR_FIND_RE = re.compile(
    r'\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]{3,9})\s+'
    r'(\d{4}|\d{2})\b')
# <Month> <day>,? <year> — 'March 15, 2024', 'Mar 15 24'.
_MONTH_DAY_YEAR_FIND_RE = re.compile(
    r'\b([A-Za-z]{3,9})(,)?\s+(\d{1,2})(,)?\s+(\d{4}|\d{2})\b')
# <Month> <year> — 'March 2024', 'Mar 24'.
_MONTH_YEAR_FIND_RE = re.compile(r'\b([A-Za-z]{3,9})\s+(\d{4}|\d{2})\b')
# <day> <Month> — '27 Oct' (year omitted -> the current year).
_DAY_MONTH_FIND_RE = re.compile(
    r'\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\b')

_DATE_SHAPE_FINDERS = [
    (_NUMERIC_FIND_RE, None),
    (_DAY_MONTH_YEAR_FIND_RE, 2),
    (_MONTH_DAY_YEAR_FIND_RE, 1),
    (_MONTH_YEAR_FIND_RE, 1),
    (_DAY_MONTH_FIND_RE, 2),
]


def _dateparser_languages():
    """dateparser language codes from Django i18n.

    The application language (the active request language or
    settings.LANGUAGE_CODE) drives date parsing so the pipeline follows
    the deployment's locale. dateparser uses ISO-639-1 style codes
    ('en', 'fr', ...; a few languages use hyphenated codes such as
    'zh-hans'), so the full code is tried first, then the base code, then
    'en'.
    """
    from django.utils import translation
    code = (translation.get_language()
            or getattr(settings, 'LANGUAGE_CODE', 'en') or 'en').lower()
    for cand in (code, code.split('-')[0]):
        if cand in _DATEPARSER_LANGUAGES:
            return [cand]
    return ['en']


def _dateparser_settings():
    """Deterministic dateparser settings for the shift pre-pass.

    PREFER_DAY_OF_MONTH / PREFER_MONTH_OF_YEAR 'first': a missing day
    defaults to the 1st, a missing month to January — partial dates parse
    identically on every run (the default 'current' anchors them to
    today). Dates are parsed as naive datetimes.
    """
    return {
        'PREFER_DAY_OF_MONTH': 'first',
        'PREFER_MONTH_OF_YEAR': 'first',
        'RETURN_AS_TIMEZONE_AWARE': False,
    }


# Candidate formats tried by parse() in order (the first that fits wins):
# day-first numeric (the clinical / en-GB convention), year-first (ISO),
# day + month name + year, month name + day + year, month name + day,
# month name + year, day + month name. Time-of-day (' 14:30', ', 2:30 pm')
# is picked up automatically after a matching date format, so no time
# suffixes are listed here.
_DATE_FORMATS = [
    '%d/%m/%Y', '%d/%m/%y',
    '%d.%m.%Y', '%d.%m.%y',
    '%d-%m-%Y', '%d-%m-%y',
    '%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d',
    '%d %b %Y', '%d %b %y', '%d %B %Y', '%d %B %y',
    '%d %b, %Y', '%d %b, %y', '%d %B, %Y', '%d %B, %y',
    '%b %d %Y', '%b %d %y', '%B %d %Y', '%B %d %y',
    '%b %d, %Y', '%B %d, %Y',
    '%b %d', '%B %d',
    '%b %Y', '%B %Y', '%b %y', '%B %y',
    '%d %b', '%d %B',
]

# search_dates is the slow path — skip it on very large documents; the
# shape regexes still cover the common formats there.
_LONG_TAIL_SIZE_LIMIT = 100_000

# Label words NER models tag as DATE_TIME ('Date of registration' -> the
# word 'Date'). Not dates, not identifiers: drop, don't redact.
_DATE_LABEL_WORDS = {
    'date', 'time', 'day', 'month', 'year', 'dob',
    'date of birth', 'date of registration', 'date of consent',
    'date of admission',
}


def _has_date_component(surface):
    """True when the surface carries an explicit date component: a month
    name, a 4-digit year, or a 3-token numeric date with date separators
    (a two-digit year only counts there — '09:15:00' is a clock, not a
    date). Without this guard dateparser would resolve durations
    ('3 days'), relative phrases ('next Tuesday') and bare times against
    the current date."""
    if any(_month_number(w) for w in re.findall(r"[A-Za-z']+", surface)):
        return True
    if re.search(r'\b\d{4}\b', surface):
        return True
    if re.search(r'\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2}\b', surface):
        return True
    if re.search(r'\b\d{2}[/.-]\d{1,2}[/.-]\d{1,4}\b', surface):
        return True
    return False


def _parse_date_span(surface):
    """Parse a candidate date surface into a datetime, or None when it is
    not an absolute date.

    First pass: the explicit format list (deterministic — formats are
    tried in order, day-first first, invalid values rejected). Second
    pass: free-form dateparser under DMY order, for surfaces with
    ordinals / 'of' / extra punctuation ('16th of September, 2026'). Both
    passes run under the PREFER_*_first settings, so partial dates are
    deterministic.
    """
    if not _has_date_component(surface):
        return None
    parser_settings = _dateparser_settings()
    languages = _dateparser_languages()
    parsed = _dateparser_parse(surface, date_formats=_DATE_FORMATS,
                               languages=languages, settings=parser_settings)
    if parsed is None:
        parsed = _dateparser_parse(
            surface, languages=languages,
            settings={**parser_settings, 'DATE_ORDER': 'DMY'})
    return parsed


def _is_single_component(surface):
    """True for surfaces with a single date component — a bare year
    ('1985'), a bare day ('27') or a bare month ('Oct'). Shifting them
    would fabricate the missing parts, so they are left untouched."""
    if re.fullmatch(r'\d{1,4}', surface):
        return True
    if re.fullmatch(r"[A-Za-z']{3,9}", surface):
        return _month_number(surface) is not None
    return False


def _is_shiftable_surface(surface):
    """Strict gate for search_dates long-tail surfaces: a real month name,
    no other words besides 'of', and an explicit year token (4-digit, or a
    2-digit token beside the month name). Keeps durations ('56 years'),
    relative phrases ('in 2 weeks after the 27/10/26') and bare times
    ('09:15:00') out of the shift."""
    bare = re.sub(r'\d+\s*(?:st|nd|rd|th)', ' ', surface)
    words = [w.lower().strip("'") for w in re.findall(r"[A-Za-z']+", bare)]
    if not any(_month_number(w) for w in words):
        return False
    if any(w != 'of' and _month_number(w) is None for w in words):
        return False
    if not re.search(r'\d{4}', surface) and not re.search(r'\b\d{2}\b', bare):
        return False
    return True


def _shifted_date_text(surface: str, shift_days: int):
    """Shift a date surface by shift_days and re-emit it as DD/MM/YYYY,
    preserving any trailing time-of-day verbatim — '27 Oct 26 14:30'
    becomes '03/11/2026 14:30' (only the date part moves). Returns None
    when the surface is not a shiftable date; callers then leave the
    content untouched (the pipeline never redacts dates)."""
    stripped = surface.strip()
    if _is_single_component(stripped):
        return None
    time_match = _TIME_SUFFIX_RE.search(stripped)
    time_part = ''
    date_part = stripped
    if time_match:
        (date_part, time_part) = (
            stripped[:time_match.start()].rstrip(),
            stripped[time_match.start():])
    parsed = _parse_date_span(date_part)
    if parsed is None:
        return None
    shifted = parsed + timezone.timedelta(days=shift_days)
    return shifted.strftime('%d/%m/%Y') + time_part


def _shift_dates_pre_pass(text, shift, replacements):
    """Pre-NER pass (before the deidentification flow begins): shift every
    absolute date span in `text` in place.

    Candidates come from the shape finders (precise spans) and from
    dateparser search_dates (long-tail recall, strictly gated). Each
    candidate is parsed with _parse_date_span — validation happens BEFORE
    the span is recorded, so an invalid candidate can never swallow a
    real date in the leftmost-longest dedup — then re-emitted as
    DD/MM/YYYY (time-of-day preserved verbatim). Returns (new_text,
    ranges) where ranges are (start, end) pairs in new_text coordinates —
    the NER stage drops spans fully contained in them (a mislabelled
    PERSON/ORG tag cannot swallow a shifted date). (original, shifted)
    pairs are appended to `replacements` for the review map.
    """
    spans = {}
    for regex, month_group in _DATE_SHAPE_FINDERS:
        for m in regex.finditer(text):
            surface = m.group(0)
            start, end = m.span()
            if start in spans and spans[start][0] - start >= end - start:
                continue
            if month_group is not None and \
                    _month_number(m.group(month_group)) is None:
                continue
            if _parse_date_span(surface) is None:
                continue
            spans[start] = (end, surface)

    # Secondary recall via dateparser for surfaces the shapes don't cover
    # (e.g. '16th September, 2026'). The gate in _is_shiftable_surface
    # keeps durations / relative phrases / bare times out. The ngram
    # strategy is required — the default 'split' strategy misses
    # dot-separated ('27.10.2026') and ISO ('2026-10-27') dates.
    if len(text) <= _LONG_TAIL_SIZE_LIMIT:
        try:
            hits = _search_dates_lib(
                text, languages=_dateparser_languages(),
                settings={**_dateparser_settings(), 'DATE_ORDER': 'DMY'},
                strategy='ngram')
        except Exception:
            hits = None
        for raw_surface, _parsed in hits or []:
            tm = _TIME_SUFFIX_RE.search(raw_surface)
            if tm:
                raw_surface = raw_surface[:tm.start()].rstrip(',;')
            if not raw_surface.strip():
                continue
            if not _is_shiftable_surface(raw_surface):
                continue
            pos = text.find(raw_surface)
            while pos != -1:
                end = pos + len(raw_surface)
                if not any(pos < e and end > s
                           for s, (e, *_rest) in spans.items()):
                    if _parse_date_span(raw_surface) is not None:
                        spans[pos] = (end, raw_surface)
                pos = text.find(raw_surface, end)

    # Leftmost, longest wins; splice right-to-left so earlier offsets
    # stay valid.
    ordered = sorted(
        spans.items(), key=lambda kv: (kv[0], -(kv[1][0] - kv[0])))
    kept = []
    for start, span in ordered:
        if not kept or start >= kept[-1][1][0]:
            kept.append((start, span))

    new_text = text
    ranges = []
    for start, (end, surface) in reversed(kept):
        new_surface = _shifted_date_text(surface, shift)
        if new_surface is None:
            continue
        if replacements is not None:
            replacements.append({
                'tag': new_surface, 'type': 'DATE_TIME',
                'original': surface})
        new_text = new_text[:start] + new_surface + new_text[end:]
        ranges.append((start, start + len(new_surface)))
    return new_text, ranges


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

        # Per-row patient (CSV row documents carry their own patient, exact
        # matched at expansion) wins; whole-file documents use the upload's.
        patient = processed_text.patient_id or processed_text.file_upload.patient_id
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
            new_content, entities, repl = cls._deidentify_text(
                content, shift, patient, ner_recognizer)
            columns = []
            deid_pipeline_row = None
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
            patient_id=processed_text.patient_id,
            content_length=len(new_content),
            version=version,
            processed_by_user=user,
            deidentified=True,
            deidentified_source=processed_text,
            deid_review_required=processed_text.deid_review_required,
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

    @staticmethod
    def _drop_date_time_and_covered(results, ranges):
        """Post date-shift policy:

        - DATE_TIME is never redacted or re-written: the pre-pass already
          shifted every absolute date, and whatever the NER still labels
          DATE_TIME (already-shifted spans, relative phrases, durations,
          label words like a bare 'Date') is kept verbatim. Recognizer
          surfaces routinely stretch over surrounding text (e.g. 'Dec
          1979\\nDate' — the shifted date's tail plus the next line's label
          word); replacing that raw surface would destroy the
          already-shifted date and neighbouring words, so it is dropped.
        - any other span fully inside a shifted date range is a mislabel
          (e.g. PERSON over a date) — dropped so it cannot swallow the
          shifted date.
        """
        if not ranges:
            return [r for r in results if r.entity_type != 'DATE_TIME']

        def covered(r):
            return any(s <= r.start and r.end <= e for s, e in ranges)

        return [r for r in results
                if r.entity_type != 'DATE_TIME' and not covered(r)]

    @classmethod
    def _deidentify_text(cls, content, shift, patient, ner_recognizer=None):
        if ner_recognizer is not None:
            analyzer = cls._get_llm_analyzer()
        else:
            analyzer, _ = cls._get_analyzer()
        ad_hoc = build_patient_recognizers(patient)
        if ner_recognizer is not None:
            ad_hoc = [ner_recognizer] + ad_hoc
        repl = []
        content, date_ranges = _shift_dates_pre_pass(content, shift, repl)
        results = analyzer.analyze(
            text=content,
            language='en',
            score_threshold=getattr(
                settings, 'EXTRACTOR_DEID_SCORE_THRESHOLD', 0.35),
            ad_hoc_recognizers=ad_hoc,
        )
        results = cls._drop_date_time_and_covered(
            cls._filter_results(content, results), date_ranges)
        results = cls._resolve_overlaps(results)
        new_content = cls._apply_replacements(
            content, results, {}, repl)
        counts = cls._entity_counts(results)
        if date_ranges:
            counts['DATE_TIME'] = counts.get('DATE_TIME', 0) + len(date_ranges)
        return new_content, counts, repl

    _analyzer_cache = {}

    @classmethod
    def _build_analyzer_for(cls, pipeline, use_cache=True):
        import os
        key = (pipeline.ner_engine,
               pipeline.hf_model_id if pipeline.ner_engine == 'hf' else None,
               pipeline.hf_threshold)
        if use_cache and key in cls._analyzer_cache:
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
        if use_cache:
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
        repl = []
        content, date_ranges = _shift_dates_pre_pass(content, shift, repl)
        results = analyzer.analyze(
            text=content, language='en',
            score_threshold=pipeline.min_confidence,
            ad_hoc_recognizers=ad_hoc)
        results = cls._drop_date_time_and_covered(
            cls._apply_precision(content, results, pipeline), date_ranges)
        results = cls._resolve_overlaps(results)
        new_content = cls._apply_replacements(content, results, {}, repl)
        counts = cls._entity_counts(results)
        if date_ranges:
            counts['DATE_TIME'] = counts.get('DATE_TIME', 0) + len(date_ranges)
        return new_content, counts, repl

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
        and the fraction counter. Note: this only shapes what reaches the
        overlap resolver — the pipeline never redacts dates: the pre-pass
        already shifted every absolute date, and remaining DATE_TIME hits
        are dropped in _drop_date_time_and_covered.
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
                    and surface.lower() in _DATE_LABEL_WORDS):
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
    def _apply_replacements(cls, text, results, tag_map,
                            replacements=None):
        """Splice replacements right-to-left; consistent numbered tags.

        DATE_TIME results are a no-op (dates are never redacted — the
        pre-pass already shifted them); anything that slips through is
        left untouched. Tags are assigned in document order (first
        occurrence = _1) before the right-to-left splice that keeps
        offsets valid. Every splice is recorded in `replacements`
        ({tag, type, original}) so the review UI can show and undo what
        each tag hid.
        """
        results = [r for r in results if r.entity_type != 'DATE_TIME']
        for r in sorted(results, key=lambda r: r.start):
            cls._tag_for(r.entity_type, text[r.start:r.end], tag_map)
        for r in sorted(results, key=lambda r: r.start, reverse=True):
            original = text[r.start:r.end]
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
