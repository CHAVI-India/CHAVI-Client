"""Central defaults for the text deid rule bundle (leaf module, no model deps).

Shared by ``extractor.models`` (the pipeline's default ``rules``) and
``extractor.services.text_deidentification`` (the ``rules=None`` fallback), so
there is a single source of truth and no circular import.
"""

import copy

DROP_ENTITY_TYPES = ['ID', 'AGE', 'NRP']

CLINICAL_ALLOWLIST = [
    'nottingham', 'grade i', 'grade ii', 'grade iii', 'grade iv',
    'mammogram', 'mammography', 'ce', 'cea', 'fnac', 'fna',
    'hourly', 'spo2', 'jvp',
]

# regexes that mark a DATE_TIME hit as a duration/age/dose -> KEEP, not redact
DATE_KEEP_PATTERNS = [
    r'^\d{1,3}%?$',
    r'^(?:age\b:?\s*)?\d{1,3}\s*[-\s]?(years?\s+old|yrs?\s+old|years?|yrs?|y/o|y\.o\.|-?year-?old)\.?$',
    r'^age\b:?\s*\d{1,3}\s*(years?|yrs?)?\.?$',
    r'^\d{1,3}\s*(years?|yrs?|y)?\s*/\s*[MF]\b\.?$',
    r'^[MF]\s*/\s*\d{1,3}\s*(years?|yrs?|y)?\b\.?$',
    r'^\d{1,3}(?:\s*-\s*\d{1,3})?\s+(years?|months?|mnths?|mths?|mos?|weeks?|wks?|days?|hrs?|hours?|mins?|minutes?)\b\.?$',
    r'^\d{1,3}\s*/\s*min\b\.?$',
    r'^\d{1,2}:\d{2}$',
    r'^(?!(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december)\b)[a-z][a-z]+\s+\d+(?:\.\d+)?\s*(g|mg|gm|ml)?\b\.?$',
]

# NOTE: no trailing `$` — matches the *prefix* of the surface (shipped behaviour)
CLINICAL_PREFIX_PATTERN = (
    r'^(hb|h\.b\.?|tabs?\b|inj\b|caps?\b|iv\b|po\b|oral\b|spo2?|s\.p\.o|jvp'
    r'|ef\b|bp\b|pr\b|hr\b|wt\b|lmp\b)')

LOCATION_RULES = {'min_length': 4, 'reject_lowercase': True,
                  'pattern': r'^[A-Za-z]?-?\d[\w-]*$'}

HF_LABEL_MAP_DEFAULT = {
    'PATIENT': 'PERSON', 'HCW': 'PERSON',
    'HOSPITAL': 'ORGANIZATION', 'VENDOR': 'ORGANIZATION',
    'ID': 'MEDICAL_RECORD_NUMBER',
    'DATE': 'DATE_TIME',
    'PHONE': 'PHONE_NUMBER',
}


def default_rules():
    return copy.deepcopy({
        'drop_entity_types': DROP_ENTITY_TYPES,
        'clinical_allowlist': CLINICAL_ALLOWLIST,
        'date_keep_patterns': DATE_KEEP_PATTERNS,
        'clinical_prefix_pattern': CLINICAL_PREFIX_PATTERN,
        'location': LOCATION_RULES,
    })


def default_hf_label_map():
    return copy.deepcopy(HF_LABEL_MAP_DEFAULT)
