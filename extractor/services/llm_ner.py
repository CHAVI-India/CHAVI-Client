"""LLM-based NER for the text deidentification pipeline.

An alternative to the HuggingFace/Stanford NER recognizer: a local
LLM (e.g. Gemma via Ollama) reads each chunk of the document and returns
entity type + VERBATIM span only. Offsets are never trusted from the
model — each span is located in the source text by search, with
duplicate spans consumed in order against successive occurrences.
Spans that cannot be located are dropped (logged), never guessed.
"""

import logging
import re
from bisect import bisect_right

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_CHARS = 3500
DEFAULT_CHUNK_OVERLAP = 256
LLM_NER_SCORE = 0.9
MAX_ENTITIES_PER_SOURCE = 400


class LlmNerError(Exception):
    """LLM call or config problem — deid run must fail, not degrade."""


# model-side type name (lowercase) -> Presidio entity used by the pipeline
ENTITY_TYPES = {
    'person': 'PERSON', 'name': 'PERSON', 'patient': 'PERSON',
    'doctor': 'PERSON', 'relative': 'PERSON',
    'location': 'LOCATION', 'place': 'LOCATION', 'address': 'LOCATION',
    'village': 'LOCATION', 'city': 'LOCATION', 'state': 'LOCATION',
    'organization': 'ORGANIZATION', 'org': 'ORGANIZATION',
    'hospital': 'ORGANIZATION', 'clinic': 'ORGANIZATION', 'lab': 'ORGANIZATION',
    'phone': 'PHONE_NUMBER', 'phone_number': 'PHONE_NUMBER',
    'telephone': 'PHONE_NUMBER',
    'date': 'DATE_TIME', 'date_time': 'DATE_TIME', 'dob': 'DATE_TIME',
    'medical_record_number': 'MEDICAL_RECORD_NUMBER', 'mrn': 'MEDICAL_RECORD_NUMBER',
    'uhid': 'MEDICAL_RECORD_NUMBER', 'registration_number': 'MEDICAL_RECORD_NUMBER',
    'aadhaar': 'IN_AADHAAR', 'aadhar': 'IN_AADHAAR',
    'mobile': 'IN_MOBILE_NUMBER', 'mobile_number': 'IN_MOBILE_NUMBER',
    'phone_mobile': 'IN_MOBILE_NUMBER',
    'pincode': 'IN_PINCODE', 'pin_code': 'IN_PINCODE', 'postal_code': 'IN_PINCODE',
    'abha': 'IN_ABHA', 'upi': 'IN_UPI',
    'driving_license': 'IN_DRIVING_LICENSE', 'driving_licence': 'IN_DRIVING_LICENSE',
    'religion': 'IN_RELIGION', 'caste': 'IN_RELIGION',
}

NER_SYSTEM_PROMPT = """You are a medical de-identification model. You find
personally identifiable information (PII/PHI) in clinical text and report
each finding as an exact verbatim copy.

Report ONLY these types:
- person: patient, relative, doctor or any other person's name
- location: village, town, city, state, street, house number, full address
- organization: hospital, clinic, lab or department name
- phone: telephone or phone number
- date: calendar dates (birth, admission, visit, report dates) in any format
- medical_record_number: MRN/UHID/registration/IP/OPD/hospital/case/report/lab numbers
- aadhaar: 12-digit Aadhaar number
- mobile: 10-digit Indian mobile number
- pincode: 6-digit Indian PIN code
- abha: ABHA/Ayushman/NHDM health ID
- upi: UPI handle (e.g. name@okhdfc)
- driving_license: driving licence number
- religion: religion or caste mention

STRICT RULES:
1. Copy each finding VERBATIM - character for character, same case, same
   spacing. Do not correct, translate, abbreviate, normalize or extend it.
2. Durations are NOT dates: "1 month", "3 days", "2 weeks", "6 months" are
   NEVER reported. Ages are never reported ("56 years old", "56-year-old").
3. Bare numbers (doses, counts, measurements, percentages) are never reported.
4. Never report anything that is not present in the text. Never guess or
   infer spans.
5. If one span fits two types, report it once with the most specific type.

Respond with a single JSON array and nothing else. Each element is
{"type": "<one of the types above>", "text": "<verbatim span>"}.
Return [] when there is no identifiable information.
No prose, no markdown fences, no offsets, no explanations."""


def chunk_text(text, max_chars=DEFAULT_CHUNK_CHARS, overlap=DEFAULT_CHUNK_OVERLAP):
    """Yield (offset, chunk) covering every character of text.

    Chunks end at a paragraph/sentence/space boundary near max_chars so
    entities are rarely split; consecutive chunks overlap by `overlap`
    characters so boundary-spanning entities are still caught, and are
    de-duplicated later by (type, global start, global end).
    """
    n = len(text)
    if n == 0:
        return
    if n <= max_chars:
        yield 0, text
        return
    start = 0
    while start < n:
        target = min(start + max_chars, n)
        if target == n:
            yield start, text[start:]
            break
        window = text[start:target]
        cut = -1
        for sep in ('\n\n', '\n', '. ', '; ', ' '):
            idx = window.rfind(sep)
            if idx > max(64, max_chars // 2):
                cut = start + idx + len(sep)
                break
        if cut <= start + 64:
            cut = target
        yield start, text[start:cut]
        start = max(cut - overlap, start + 1)


class _SourceIndex:
    """Locates verbatim spans in a source string.

    Three strategies in order: exact find, whitespace-collapsed find
    (handles line-broken names like 'Sharma\\nRao'), then case-insensitive
    variants of both. Returns offsets into the ORIGINAL string.
    """

    __slots__ = ('source', 'source_lower', 'collapsed', 'collapsed_lower', 'pos_map')

    def __init__(self, source):
        self.source = source
        self.source_lower = source.lower()
        chars = []
        self.pos_map = []
        for i, ch in enumerate(source):
            if not ch.isspace():
                chars.append(ch)
                self.pos_map.append(i)
        self.collapsed = ''.join(chars)
        self.collapsed_lower = self.collapsed.lower()

    def _collapsed_from(self, from_pos):
        """First collapsed-coordinate index whose original pos >= from_pos."""
        return bisect_right(self.pos_map, from_pos - 1)

    def locate(self, span, from_pos=0, case_sensitive=True):
        span = span or ''
        if not span.strip():
            return None
        # 1. exact
        if case_sensitive:
            idx = self.source.find(span, from_pos)
        else:
            idx = self.source_lower.find(span.lower(), from_pos)
        if idx != -1:
            return idx, idx + len(span)
        # 2. whitespace-collapsed
        collapsed = ''.join(span.split())
        if not collapsed:
            return None
        cfrom = self._collapsed_from(from_pos)
        if case_sensitive:
            cidx = self.collapsed.find(collapsed, cfrom)
        else:
            cidx = self.collapsed_lower.find(collapsed.lower(), cfrom)
        if cidx == -1 or cidx + len(collapsed) > len(self.pos_map):
            return None
        start = self.pos_map[cidx]
        end = self.pos_map[cidx + len(collapsed) - 1] + 1
        return start, end


def resolve_spans(source, found):
    """Map ordered model output to offsets in `source`.

    `found`: list of (presidio_entity_type, verbatim_span) in the order the
    model reported them. Offsets are computed here — the model never
    reports them. Duplicate (type, span) pairs are consumed in order: the
    k-th report searches from just after the (k-1)-th match, so repeated
    names bind to successive occurrences. Exact matching is tried first,
    then whitespace-collapsed, then case-insensitive variants. Spans that
    cannot be located are dropped with a warning. Returns
    [{'type', 'start', 'end'}] sorted by position.
    """
    index = _SourceIndex(source)
    next_from = {}  # (type, normalized span) -> search start in original coords
    out = []
    seen = set()
    for entity_type, span in found:
        norm = ' '.join((span or '').split()).lower()
        if not norm:
            continue
        key = (entity_type, norm)
        from_pos = next_from.get(key, 0)
        match = index.locate(span, from_pos, case_sensitive=True)
        if match is None:
            match = index.locate(span, from_pos, case_sensitive=False)
        if match is None:
            logger.warning(
                'LLM NER span not found in source, dropped: %r', span)
            continue
        start, end = match
        next_from[key] = end
        pos_key = (entity_type, start, end)
        if pos_key in seen:
            continue
        seen.add(pos_key)
        out.append({'type': entity_type, 'start': start, 'end': end})
        if len(out) >= MAX_ENTITIES_PER_SOURCE:
            logger.warning(
                'LLM NER entity cap (%d) reached; remaining spans dropped',
                MAX_ENTITIES_PER_SOURCE)
            break
    return sorted(out, key=lambda e: (e['start'], e['end']))
