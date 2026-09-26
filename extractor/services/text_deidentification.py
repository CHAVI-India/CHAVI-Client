"""Text deidentification service for the extractor pipeline.

Runs after file processing/OCR and before extraction: produces a new
versioned ProcessedText whose content has PHI replaced by numbered generic
tags (<PERSON_1>, <IN_AADHAAR_1>, ...) and all dates shifted by a random
per-document offset stored (encrypted) on the row. save_extraction_results
subtracts that offset from extracted date fields so real dates are written
back.

The analyzer mirrors deidentification.utils.burnt_in_pixel_scrubbing's
engine build (spaCy en_core_web_lg + optional HuggingFaceNerRecognizer +
shared Indian recognizer bundle) plus text-specific recognizers from
deid_recognizers.py. Everything is extractor-local: no deidentification-app
models are touched.
"""

import csv
import io
import logging
import random
import re
from pathlib import Path

from dateutil.parser import parse as parse_date
from django.conf import settings
from django.utils import timezone
from presidio_analyzer import AnalyzerEngine, LemmaContextAwareEnhancer

from extractor.services.deid_recognizers import (
    build_patient_recognizers,
    build_text_recognizers,
)

logger = logging.getLogger(__name__)

TAG_RE = re.compile(r'<[A-Z_]+(_\d+)?>')

# surface format -> strftime code for re-emitting shifted dates
_DATE_FORMATS = [
    (re.compile(r'^\d{1,2}/\d{1,2}/\d{4}$'), '%d/%m/%Y'),
    (re.compile(r'^\d{1,2}-\d{1,2}-\d{4}$'), '%d-%m-%Y'),
    (re.compile(r'^\d{1,2}\.\d{1,2}\.\d{4}$'), '%d.%m.%Y'),
    (re.compile(r'^\d{1,2}/\d{1,2}/\d{2}$'), '%d/%m/%y'),
    (re.compile(r'^\d{4}-\d{2}-\d{2}$'), '%Y-%m-%d'),
    (re.compile(r'^\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}$'), '%d %B %Y'),
    (re.compile(r'^[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}$'), '%B %d, %Y'),
]


def _shifted_date_text(surface: str, shift_days: int) -> str:
    """Shift a date surface by shift_days, preserving its format."""
    stripped = surface.strip()
    try:
        if re.match(r'^\d{4}-\d{1,2}-\d{1,2}', stripped):
            # ISO is year-first; dayfirst=True would misparse it.
            parsed = parse_date(stripped, yearfirst=True)
        else:
            parsed = parse_date(stripped, dayfirst=True)
    except (ValueError, OverflowError):
        return '<DATE>'
    shifted = parsed + timezone.timedelta(days=shift_days)
    stripped = surface.strip()
    for regex, fmt in _DATE_FORMATS:
        if regex.match(stripped):
            if fmt == '%d %B %Y' and re.match(r'^\d{1,2}\s+[A-Za-z]{3}\s', stripped):
                fmt = '%d %b %Y'
            if fmt == '%B %d, %Y' and re.match(r'^[A-Za-z]{3}\s', stripped):
                fmt = '%b %d, %Y'
            return shifted.strftime(fmt)
    return '<DATE>'


def _normalize_tag_key(text: str) -> str:
    return ' '.join(text.split()).lower()


class TextDeidentificationService:
    _analyzer = None       # lazy per-process singleton
    _engine_mode = None    # 'full' | 'degraded'

    @classmethod
    def _get_analyzer(cls):
        if cls._analyzer is None:
            cls._analyzer, cls._engine_mode = cls._build_analyzer()
        return cls._analyzer, cls._engine_mode

    @classmethod
    def _build_analyzer(cls):
        analyzer = AnalyzerEngine(
            supported_languages=["en"],
            context_aware_enhancer=LemmaContextAwareEnhancer(
                context_similarity_factor=0.35,
                min_score_with_context_similarity=0.4,
            ),
        )
        engine_mode = 'degraded'

        backend = getattr(settings, 'EXTRACTOR_DEID_NER_BACKEND', 'hf')
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
                    device="cpu",
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
    def deidentify(cls, processed_text, user=None):
        """Produce a deidentified version of a ProcessedText row.

        Returns the new ProcessedText row, or None when skipped.
        """
        from extractor.models import ProcessedText
        from extractor.services.file_processor import FileProcessorService

        if processed_text.deidentified:
            return None

        content = FileProcessorService.get_processed_content(processed_text)
        if not content:
            raise ValueError("Cannot read source processed text content")

        date_range = getattr(settings, 'EXTRACTOR_DEID_DATE_SHIFT_RANGE', 100)
        shift = random.randint(-date_range, date_range)

        patient = processed_text.file_upload.patient_id
        path = str(processed_text.processed_file_path or '')
        if path.endswith('.csv'):
            new_content, entities, columns, repl = cls._deidentify_csv(
                content, shift, patient)
        else:
            new_content, entities, repl = cls._deidentify_text(
                content, shift, patient)
            columns = []

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

        _, engine_mode = cls._get_analyzer()
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
            deid_model=(
                settings.DEID_HF_NER_MODEL if engine_mode == 'full' else ''
            ),
            deid_entities=entities,
            deid_csv_columns_flagged=columns,
            deid_map=list(deid_map.values()),
            deid_date_shift_days=shift,
        )

    @classmethod
    def deidentify_if_needed(cls, processed_text, user=None):
        """Dispatch-safe wrapper: skip when deid output already exists."""
        if not getattr(settings, 'EXTRACTOR_DEID_ENABLED', True):
            return None
        if processed_text.deid_derivatives.exists():
            return processed_text.deid_derivatives.order_by('-version').first()
        return cls.deidentify(processed_text, user=user)

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
    def _deidentify_text(cls, content, shift, patient):
        analyzer, _ = cls._get_analyzer()
        results = analyzer.analyze(
            text=content,
            language='en',
            score_threshold=getattr(
                settings, 'EXTRACTOR_DEID_SCORE_THRESHOLD', 0.35),
            ad_hoc_recognizers=build_patient_recognizers(patient),
        )
        results = cls._resolve_overlaps(cls._filter_results(content, results))
        repl = []
        new_content = cls._apply_replacements(
            content, results, shift, {}, repl)
        return new_content, cls._entity_counts(results), repl

    @classmethod
    def _deidentify_csv(cls, content, shift, patient):
        """Header-aware CSV pass: mapped columns are replaced wholesale;
        unmapped columns get per-cell NER with a shared tag map."""
        column_map = getattr(settings, 'EXTRACTOR_DEID_CSV_COLUMN_MAP', {})
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        if not rows:
            return cls._deidentify_text(content, shift, patient) + ([],)

        headers = rows[0]
        col_types = [column_map.get(h.strip().lower()) for h in headers]
        if not any(col_types):
            # No recognizable headers — treat the whole thing as text so
            # PHI in unmapped CSVs is still caught.
            new_content, counts, repl = cls._deidentify_text(
                content, shift, patient)
            return new_content, counts, [], repl

        analyzer, _ = cls._get_analyzer()
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
                        ad_hoc_recognizers=build_patient_recognizers(patient),
                    )
                    results = cls._resolve_overlaps(
                        cls._filter_results(cell, results))
                    row[i] = cls._apply_replacements(
                        cell, results, shift, tag_map, repl)
                    all_results.extend(
                        _FakeResult(r.entity_type, cell) for r in results)
            writer.writerow(row)

        return out.getvalue(), cls._entity_counts(all_results), flagged, repl

    @staticmethod
    def _filter_results(text, results):
        """Drop recognizer hits that are implausible or unwanted for text:

        - Entity types in EXTRACTOR_DEID_DROP_ENTITY_TYPES (default: ID,
          AGE — the ai4privacy catch-all labels that destroy clinical
          numerics and are not needed as PHI).
        - Bare short digits as DATE_TIME (ages, doses, counts).
        """
        drop_types = getattr(
            settings, 'EXTRACTOR_DEID_DROP_ENTITY_TYPES', {'ID', 'AGE', 'NRP'})
        kept = []
        for r in results:
            surface = text[r.start:r.end].strip()
            if r.entity_type in drop_types:
                continue
            if not surface:
                continue
            # Mid-word spans are HF tokenization artifacts (e.g. 'oph' of
            # 'oropharynx', 'ally' of 'clinically') — real PHI spans align
            # to word boundaries. Spans often include surrounding spaces,
            # so measure from the stripped surface edges.
            raw = text[r.start:r.end]
            b_start = r.start + (len(raw) - len(raw.lstrip()))
            b_end = r.end - (len(raw) - len(raw.rstrip()))
            if (b_start > 0 and text[b_start - 1].isalnum()) or \
                    (b_end < len(text) and text[b_end].isalnum()):
                continue
            # Bare digits/percentages are never real dates (ages, counts),
            # and explicit age surfaces ('56 Years', '56-year-old') are not
            # redacted — age is not a direct identifier.
            if (r.entity_type == 'DATE_TIME' and re.match(
                    r'^\d{1,3}%?$|^\d{1,3}\s*[-\s]?(years?|yrs?|y/o|y\.o\.|-?year-?old)\.?$',
                    surface, re.I)):
                continue
            if r.entity_type == 'LOCATION':
                # Specimen/grid labels (A3, A5-A10, 11-A14), lowercase words
                # ('anterior', 'trabeculae') and short tokens are never real
                # locations. Genuine address tokens (Newtown, Kolkata,
                # PIN 700160) are title-case or long digit runs and survive.
                if (len(surface) <= 3 or surface.islower()
                        or re.match(r'^[A-Za-z]?-?\d[\w-]*$', surface)):
                    continue
            kept.append(r)
        return kept

    @staticmethod
    def _resolve_overlaps(results):
        """Keep highest-scoring span among overlaps; longest wins ties."""
        if not results:
            return []
        ordered = sorted(
            results,
            key=lambda r: (-r.score, -(r.end - r.start), r.start))
        kept = []
        for r in ordered:
            if not any(r.start < k.end and r.end > k.start for k in kept):
                kept.append(r)
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
