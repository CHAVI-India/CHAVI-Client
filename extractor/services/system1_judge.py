"""System-1 decision-model judge for deid precision.

A fast decision model (e.g. Ollama 'nimble' via /v1/systemone) judges one small
span with its surrounding context: 'is this PHI?' Endpoint + model name come
from a ClientConfiguration (model_type='system1'); threshold + window come from
the pipeline. External endpoints are allowed (only short snippets are sent).
"""

import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

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


def endpoint(config):
    base = config.model_base_url.rstrip('/')
    if base.endswith('/systemone'):
        return base
    if base.endswith('/v1'):
        return base + '/systemone'
    return base + '/v1/systemone'


def build_context(text, start, end, window=90):
    surf = text[start:end]
    ws, we = max(0, start - window), min(len(text), end + window)
    excerpt = text[ws:we]
    rel = start - ws
    return excerpt[:rel] + '«' + surf + '»' + excerpt[rel + len(surf):]


def _so_post(url, model, state, questions, api_key=None, timeout=300):
    payload = json.dumps({'model': model, 'state': state,
                          'questions': questions}).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if api_key and api_key != 'ollama':
        headers['Authorization'] = f'Bearer {api_key}'
    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8')).get('answers', {})


def judge_span(config, text, start, end, threshold, window=90):
    """PHI probability (0..1) for one span. Caller compares to threshold."""
    state = {'excerpt': build_context(text, start, end, window)}
    answers = _so_post(endpoint(config), config.llm_model_name, state,
                       {'is_phi': {'type': 'noul', 'instructions': IS_PHI_QUESTION}},
                       api_key=config.model_api_key)
    return float(answers.get('is_phi', {}).get('noul', 0.0))
