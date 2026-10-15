"""
Base-URL normalization and egress policy for LLM/embedding endpoints.

Policy: https:// is allowed anywhere; http:// only for loopback or
private/LAN addresses (local Ollama-style servers), including
100.64.0.0/10 (CGNAT, used by NetBird/Tailscale VPNs).
"""

from urllib.parse import urlsplit
from ipaddress import ip_address, ip_network

from django.core.exceptions import ValidationError

# Ranges treated as "LAN" even though ipaddress.is_private doesn't cover them.
LAN_NETWORKS = (
    ip_network('100.64.0.0/10'),  # CGNAT — NetBird/Tailscale 100.x.x.x addresses
)


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

    # http:// — loopback, private LAN, or VPN/CGNAT range only
    try:
        ip = ip_address(host)
        permitted = ip.is_loopback or ip.is_private or any(ip in net for net in LAN_NETWORKS)
    except ValueError:
        permitted = host in ('localhost', 'localhost.localdomain')

    if not permitted:
        raise ValidationError(
            f"Insecure http:// {field_label} {url!r} is only allowed for "
            f"localhost/LAN endpoints. Use https://."
        )
    return url


# Provider names that denote a cloud API. Text deidentification may never
# use one: patient text must stay on the local network.
CLOUD_PROVIDERS = ('openai', 'azure', 'anthropic', 'google', 'cohere', 'mistral')


def is_cloud_provider(provider):
    p = (provider or '').lower()
    return any(name in p for name in CLOUD_PROVIDERS)


def is_local_endpoint(base_url):
    """True when the base URL points at loopback, a private/LAN address,
    or a CGNAT (NetBird/Tailscale) range. Named hosts are NOT accepted —
    locality must be provable from the address itself."""
    url = normalize_base_url(base_url)
    if not url:
        return False
    host = (urlsplit(url).hostname or '').lower()
    if host in ('localhost', 'localhost.localdomain'):
        return True
    try:
        ip = ip_address(host)
    except ValueError:
        return False
    return (ip.is_loopback or ip.is_private
            or any(ip in net for net in LAN_NETWORKS))
