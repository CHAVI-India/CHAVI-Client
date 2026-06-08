"""
Migration to enable pgvector extension in PostgreSQL.
This must run before creating tables with vector fields.
"""

from django.contrib.postgres.operations import CreateExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('extractor', '0001_initial'),
    ]

    operations = [
        # Enable pgvector extension
        CreateExtension('vector'),
    ]
