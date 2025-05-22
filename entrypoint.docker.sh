#!/bin/bash

# Wait for the database to be ready
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput


python manage.py createsuperuser --noinput --username $DJANGO_SUPERUSER_USERNAME --email $DJANGO_SUPERUSER_EMAIL

# Start the server with increased timeout settings
exec python -m gunicorn chavi_client.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 300 \
    --keep-alive 65 \
    --worker-class gthread \
    --threads 3 \
    --max-requests 1000 \
    --max-requests-jitter 50
