#!/bin/bash

# Wait for the database to be ready
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput


python manage.py createsuperuser --noinput --username $DJANGO_SUPERUSER_USERNAME --email $DJANGO_SUPERUSER_EMAIL

# Start the server
exec python -m gunicorn chavi_client.wsgi:application --bind 0.0.0.0:8000 --workers 3
