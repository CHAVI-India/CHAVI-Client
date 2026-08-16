import logging
import re

logger = logging.getLogger(__name__)

PHI_PATTERNS = [
    (re.compile(r'[\w\.-]+@[\w\.-]+\.\w+'), 'EMAIL_REMOVED'),
    (re.compile(r'https?://\S+'), 'URL_REMOVED'),
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), 'IP_REMOVED'),
    (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), 'SSN_REMOVED'),
    (re.compile(r'\b\d{9}\b'), 'SSN_REMOVED'),
    (re.compile(r'\(?\d{3}\)?[-\.\s]?\d{3}[-\.\s]?\d{4}'), 'PHONE_REMOVED'),
]


def scrub_phi_patterns(text: str) -> str:
    if not text or text == "#":
        return text

    result = text
    for pattern, replacement in PHI_PATTERNS:
        result = pattern.sub(replacement, result)

    return result
