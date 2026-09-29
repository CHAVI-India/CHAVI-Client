"""Patient-ID variation engine for remote-node queries.

Remote PACS commonly store patient IDs in a different format than the local
CHAVI patient_id (e.g. 'MR/25/004771' vs '25_004771'). Per-node transform
rules — [{'pattern': <regex>, 'replacement': <str>}] — generate candidate
remote IDs from the local ID so a single configured rule covers every
patient queried against that node.
"""
import logging
import re

logger = logging.getLogger(__name__)

SEPARATOR = '=>'


def apply_transforms(patient_id: str, transforms) -> list[str]:
    """Apply {pattern, replacement} rules to a local patient ID.

    Each rule whose regex matches produces one candidate remote ID via
    re.sub. Non-matching rules and invalid regexes are skipped (rules are
    validated upstream in forms). Returns deduped outputs, excluding the
    input itself.
    """
    out = []
    for t in transforms or []:
        if not isinstance(t, dict):
            continue
        pattern = t.get('pattern')
        replacement = t.get('replacement', '')
        if not pattern:
            continue
        try:
            rx = re.compile(pattern)
        except re.error:
            logger.warning('Invalid patient-ID transform pattern %r — skipped', pattern)
            continue
        if rx.search(patient_id):
            candidate = rx.sub(replacement, patient_id)
            if candidate and candidate != patient_id and candidate not in out:
                out.append(candidate)
    return out


def validate_transforms(transforms) -> list[str]:
    """Return a list of human-readable error strings; empty means valid."""
    errors = []
    if transforms is None:
        return errors
    if not isinstance(transforms, list):
        return ['Transform rules must be a list of {"pattern", "replacement"} objects.']
    for i, t in enumerate(transforms, 1):
        if not isinstance(t, dict) or 'pattern' not in t or 'replacement' not in t:
            errors.append(f'Rule {i}: must be an object with "pattern" and "replacement".')
            continue
        try:
            re.compile(t['pattern'])
        except (re.error, TypeError) as e:
            errors.append(f'Rule {i}: invalid regex {t.get("pattern")!r} ({e}).')
    return errors


def parse_transform_lines(text: str) -> list[dict]:
    """Parse 'pattern => replacement' lines (one rule per line) into
    transform dicts. Blank lines and lines starting with '#' are ignored;
    lines without '=>' yield an empty replacement (caught by validation)."""
    transforms = []
    for raw in (text or '').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        pattern, sep, replacement = line.partition(SEPARATOR)
        transforms.append({
            'pattern': pattern.strip(),
            'replacement': replacement.strip() if sep else '',
        })
    return transforms


def transforms_to_lines(transforms) -> str:
    """Render stored transform dicts back to 'pattern => replacement' lines
    for textarea editing."""
    return '\n'.join(
        f"{t.get('pattern', '')} {SEPARATOR} {t.get('replacement', '')}"
        for t in (transforms or [])
    )
