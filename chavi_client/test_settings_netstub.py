"""Temporary test settings: redirect lookup-data CSV migrations to a local
mirror so the suite can build its test DB without hitting the (rate-limited)
GitLab raw endpoint. No production migration file is modified; pandas.read_csv
is monkeypatched for this process only. Use:
    DJANGO_SETTINGS_MODULE=chavi_client.test_settings_netstub manage.py test extractor
"""
from chavi_client.settings import *  # noqa: F403
import os
import pandas as pd

_LOCAL_ROOT = os.environ.get(
    'CHAVI_LOOKUP_LOCAL_ROOT', '/mnt/share/chavi_lookups/')
_MARKER = '/lookup_datasets/'
_orig_read_csv = pd.read_csv


def _patched_read_csv(src, *args, **kwargs):
    if isinstance(src, str) and 'gitlab.com' in src and _MARKER in src:
        rel = src.split(_MARKER, 1)[1].split('?', 1)[0]
        local = os.path.join(_LOCAL_ROOT, 'lookup_datasets', rel)
        if os.path.exists(local):
            return _orig_read_csv(local, *args, **kwargs)
    return _orig_read_csv(src, *args, **kwargs)


pd.read_csv = _patched_read_csv

ALLOWED_HOSTS = list(ALLOWED_HOSTS) + ['testserver']
