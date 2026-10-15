"""OpenMed local clinical PII NER as a Presidio ad-hoc recognizer.

OpenMed (Apache-2.0) ships HuggingFace token-classification models
trained on clinical/PII data (Nemotron-PII label set, 54 types). Unlike
general-domain NER (spaCy en_core_web_lg) it does not redact clinical
terminology ("Nottingham", "Grade III", "mammogram", "HER2 3+") while
still catching names, places, dates and record numbers — including
small places (village names) that the Stanford deid model misses.

The model runs locally (HF weights, CPU). Like the LLM recognizer it is
plugged in as an ad-hoc recognizer on the rules-only analyzer, so all
downstream pipeline logic (filters, overlap resolution, date shifting,
tags, review map) is unchanged.

Integration notes:
- ``extract_pii`` returns true character offsets, so no verbatim-span
  search is needed (unlike the LLM engine).
- Only a curated label subset is mapped to Presidio entity types;
  everything else (medical_condition, user_name, credit_debit_card,
  ...) is dropped — structured Indian IDs are covered by the
  deterministic rule recognizers.
- The ``age`` label maps to Presidio AGE and is dropped by the usual
  EXTRACTOR_DEID_DROP_ENTITY_TYPES filter (ages are clinical content
  in these records, not reportable PII here).
"""

import logging

from presidio_analyzer import LocalRecognizer, RecognizerResult

logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'pii_superclinical_large'
DEFAULT_THRESHOLD = 0.55

# Nemotron-PII label -> Presidio entity type. Unmapped labels are
# dropped (medical_condition, credit_debit_card, user_name,
# biometric_identifier, ... are not PHI for this pipeline).
LABEL_MAP = {
    'first_name': 'PERSON',
    'last_name': 'PERSON',
    'name': 'PERSON',
    'age': 'AGE',  # dropped by EXTRACTOR_DEID_DROP_ENTITY_TYPES
    'address': 'LOCATION',
    'city': 'LOCATION',
    'state': 'LOCATION',
    'country': 'LOCATION',
    'postcode': 'LOCATION',
    'date': 'DATE_TIME',
    'date_of_birth': 'DATE_TIME',
    'phone': 'PHONE_NUMBER',
    'phone_number': 'PHONE_NUMBER',
    'email': 'EMAIL_ADDRESS',
    'email_address': 'EMAIL_ADDRESS',
    'medical_record_number': 'MEDICAL_RECORD_NUMBER',
    'health_plan_beneficiary_number': 'MEDICAL_RECORD_NUMBER',
    'national_id': 'NATIONAL_ID',
    'ssn': 'NATIONAL_ID',
    'driver_license': 'NATIONAL_ID',
    'passport': 'NATIONAL_ID',
    'tax_id': 'TAX_ID_INCOME',
    'ip_address': 'IP_ADDRESS',
    'url': 'URL',
}


class OpenMedNerError(Exception):
    """OpenMed call/model problem — deid run must fail, not degrade."""


class OpenMedNerRecognizer(LocalRecognizer):
    """Presidio adapter so OpenMed plugs into the existing analyzer as an
    ad-hoc recognizer. Per-run instance (like LlmNerRecognizer) —
    OpenMed caches the model in-process, so repeated calls are cheap.
    A per-run text cache keeps repeated CSV cells at one inference.
    """

    def __init__(self, model_name=None, threshold=None, cache=None):
        from django.conf import settings

        super().__init__(
            supported_entities=sorted(set(LABEL_MAP.values())),
            name='OpenMedNerRecognizer',
            supported_language='en',
        )
        self._model_name = model_name or getattr(
            settings, 'EXTRACTOR_DEID_OPENMED_MODEL', DEFAULT_MODEL)
        self._threshold = (
            threshold
            if threshold is not None
            else getattr(
                settings, 'EXTRACTOR_DEID_OPENMED_THRESHOLD',
                DEFAULT_THRESHOLD))
        self._cache = cache if cache is not None else {}

    def analyze(self, text, entities=None, nlp_artifacts=None, **kwargs):
        if not text or not text.strip():
            return []
        found = self._cache.get(text)
        if found is None:
            found = self._find(text)
            self._cache[text] = found
        return [
            RecognizerResult(entity_type=t, start=s, end=e, score=sc)
            for t, sc, s, e in found
        ]

    def evaluate(self, **kwargs):
        return []

    def _find(self, text):
        """One inference -> [(presidio_type, score, start, end)]."""
        try:
            hits = self._extract(text)
        except OpenMedNerError:
            raise
        except Exception as e:
            raise OpenMedNerError(
                f'OpenMed NER call failed for model {self._model_name!r}: '
                f'{e}') from e
        out = []
        for label, conf, start, end in hits:
            entity_type = LABEL_MAP.get(label)
            if entity_type is None:
                continue
            if conf < self._threshold:
                logger.debug(
                    'OpenMed NER below threshold dropped: %s %r %.2f',
                    label, text[start:end], conf)
                continue
            out.append((entity_type, conf, start, end))
        return out

    def _extract(self, text):
        """Model seam (patched in tests). Returns
        [(label, confidence, start, end)] with true char offsets."""
        from openmed import extract_pii
        result = extract_pii(
            text, model_name=self._model_name, use_smart_merging=True)
        return [
            (e.label, float(e.confidence), int(e.start), int(e.end))
            for e in result.entities
        ]
