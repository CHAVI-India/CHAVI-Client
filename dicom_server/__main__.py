"""Standalone entrypoint: python -m dicom_server

Boots Django, waits for the database, then runs the DICOM SCP.
"""
import os
import sys
import time

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chavi_client.settings')
django.setup()

from django.db import connections  # noqa: E402

for _attempt in range(60):
    try:
        connections['default'].ensure_connection()
        break
    except Exception:
        time.sleep(2)
else:
    sys.exit('Database never became available')

from dicom_server.scp.server import run_server  # noqa: E402

run_server()
