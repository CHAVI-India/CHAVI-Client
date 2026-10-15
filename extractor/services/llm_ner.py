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

from presidio_analyzer import LocalRecognizer, RecognizerResult

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_CHARS = 3500
DEFAULT_CHUNK_OVERLAP = 256
LLM_NER_SCORE = 0.9
MAX_ENTITIES_PER_SOURCE = 400


class LlmNerError(Exception):
    """LLM call or config problem — deid run must fail, not degrade."""


class LlmNerParseError(Exception):
    """Internal: model output was not recoverable JSON."""


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


def _parse_entity_output(content):
    """Lenient parse of a model JSON response.

    Small models are inconsistent about wrapping: accept a JSON array
    of {"type", "text"}, an object with an 'entities' key, or a single
    {"type", "text"} object; strip code fences and surrounding prose by
    taking the outermost JSON value. Returns [(raw_type, span)]; raises
    LlmNerParseError when no JSON can be recovered.
    """
    import json

    text = (content or '').strip()
    if text.startswith('```'):
        text = text.strip('`').strip()
        if text.lower().startswith('json'):
            text = text[4:].strip()

    candidates = [text]
    for open_ch, close_ch in (('[', ']'), ('{', '}')):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if start != -1 and end > start:
            candidates.append(text[start:end + 1])

    for cand in candidates:
        try:
            data = json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            data = data.get('entities', [data])
        if not isinstance(data, list):
            continue
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            out.append((str(item.get('type', '')), str(item.get('text', ''))))
        return out
    raise LlmNerParseError(f'unparseable model output: {content[:200]!r}')


def _normalize_entity_type(raw):
    """Model type string -> Presidio entity, or None for unknown types."""
    key = re.sub(r'[^a-z0-9]+', '_', (raw or '').strip().lower()).strip('_')
    return ENTITY_TYPES.get(key)


class LlmNerClient:
    """Chat-completion client for the deid NER role.

    Uses the same OpenAI-compatible wiring as the extraction pipeline
    (base_url + /v1, 'ollama' dummy key for local providers). The model
    must return a JSON array of {"type", "text"}; offsets are computed
    by resolve_spans, never parsed from the response.
    """

    def __init__(self, client_config):
        from openai import OpenAI
        from extractor.services.url_policy import validate_base_url

        base_url = validate_base_url(
            client_config.model_base_url, 'model base URL')
        if not base_url.endswith('/v1'):
            base_url = f'{base_url}/v1'
        provider = (client_config.model_provider or '').lower()
        is_local = 'ollama' in provider or 'local' in provider
        self._client = OpenAI(
            base_url=base_url,
            api_key='ollama' if is_local else client_config.model_api_key,
            timeout=client_config.request_timeout,
        )
        self._model = client_config.llm_model_name

    def _llm_call(self, chunk):
        """One chat call -> the model's raw output as
        [(raw_type, verbatim_span)] — entity-type mapping happens in
        find_entities. Small models need lenient parsing (array / 'entities'
        object / single object), so this is a raw JSON-mode-less call with
        a strict prompt, retried once on unparseable output. Isolated as a
        method so tests can patch the network boundary. Call errors
        propagate to find_entities, which converts them to LlmNerError.
        """
        last_error = None
        for _attempt in (1, 2):
            try:
                content = self._raw_chat(chunk)
                return _parse_entity_output(content)
            except LlmNerParseError as e:
                last_error = e
        raise LlmNerParseError(
            f'LLM NER returned unparseable JSON for model {self._model!r} '
            f'after 2 attempts: {last_error}')

    def _raw_chat(self, chunk):
        completion = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {'role': 'system', 'content': NER_SYSTEM_PROMPT},
                {'role': 'user', 'content': chunk},
            ],
            temperature=0,
        )
        return completion.choices[0].message.content or ''

    def find_entities(self, chunk):
        """One chunk -> [(presidio_type, verbatim_span)].

        Maps the model's type names onto the pipeline's Presidio
        entities; unknown types are dropped with a warning. Any failure
        at the network boundary becomes LlmNerError so a deid run fails
        loudly rather than emitting under-redacted output.
        """
        try:
            raw = self._llm_call(chunk)
        except LlmNerError:
            raise
        except Exception as e:
            raise LlmNerError(
                f'LLM NER call failed for model {self._model!r}: {e}') from e
        out = []
        for raw_type, span in raw:
            entity_type = _normalize_entity_type(raw_type)
            if entity_type is None:
                logger.warning(
                    'LLM NER unknown entity type dropped: %r', raw_type)
                continue
            out.append((entity_type, span))
        return out

    def find_entities_in_text(self, text):
        """Whole text -> [{'type','start','end','score'}] with global,
        de-duplicated offsets (overlapping chunks re-find boundary
        entities; duplicates collapse on (type, start, end))."""
        if not text or not text.strip():
            return []
        results = []
        seen = set()
        for offset, chunk in chunk_text(text):
            for found in resolve_spans(chunk, self.find_entities(chunk)):
                start, end = found['start'] + offset, found['end'] + offset
                key = (found['type'], start, end)
                if key in seen:
                    continue
                seen.add(key)
                results.append({
                    'type': found['type'], 'start': start, 'end': end,
                    'score': LLM_NER_SCORE,
                })
        return sorted(results, key=lambda r: (r['start'], r['end']))


class LlmNerRecognizer(LocalRecognizer):
    """Presidio adapter so the LLM plugs into the existing analyzer as an
    ad-hoc recognizer — all downstream deid logic (filters, overlap
    resolution, date shifting, tagging, CSV handling) is unchanged.

    Results carry no context enhancement (the LLM already applied
    context); they pass the analyzer's threshold untouched at
    LLM_NER_SCORE (0.9), which outranks rule recognizers' moderate
    scores while deterministic patterns (e.g. 0.95 MRN) still win.
    """

    def __init__(self, client_config, cache=None):
        super().__init__(
            supported_entities=sorted(set(ENTITY_TYPES.values())),
            name='LlmNerRecognizer',
            supported_language='en',
        )
        self._client = LlmNerClient(client_config)
        self._cache = cache if cache is not None else {}

    def analyze(self, text, entities=None, nlp_artifacts=None, **kwargs):
        if not text or not text.strip():
            return []
        found = self._cache.get(text)
        if found is None:
            found = self._client.find_entities_in_text(text)
            self._cache[text] = found
        return [
            RecognizerResult(entity_type=e['type'], start=e['start'],
                             end=e['end'], score=e['score'])
            for e in found
        ]

    def evaluate(self, **kwargs):
        return []
