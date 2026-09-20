"""
Base-URL normalization and egress policy for LLM/embedding endpoints.

Policy: https:// is allowed anywhere; http:// only for loopback or
private/LAN addresses (local Ollama-style servers).
"""

from urllib.parse import urlsplit
from ipaddress import ip_address

from django.core.exceptions import ValidationError


def normalize_base_url(value):
    """
    Normalize a base URL: strip whitespace/trailing slashes, add http://
    when no scheme is present. Returns None for blank input.
    """
    if not value:
        return None
    url = str(value).strip().rstrip('/')
    if not url:
        return None
    if not url.startswith(('http://', 'https://')):
        url = f'http://{url}'
    return url


def validate_base_url(value, field_label='base URL'):
    """
    Raise ValidationError unless the URL passes the egress policy.
    """
    url = normalize_base_url(value)
    if not url:
        raise ValidationError(f"A {field_label} is required.")

    host = (urlsplit(url).hostname or '').lower()
    if not host:
        raise ValidationError(f"Invalid {field_label}: {value!r}")

    if url.startswith('https://'):
        return url

    # http:// — loopback or private LAN only
    try:
        ip = ip_address(host)
        permitted = ip.is_loopback or ip.is_private
    except ValueError:
        permitted = host in ('localhost', 'localhost.localdomain')

    if not permitted:
        raise ValidationError(
            f"Insecure http:// {field_label} {url!r} is only allowed for "
            f"localhost/LAN endpoints. Use https://."
        )
    return url
