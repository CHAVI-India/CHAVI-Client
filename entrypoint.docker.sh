#!/bin/bash

# Wait for the database to be ready
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput

python manage.py createsuperuser --noinput --username $DJANGO_SUPERUSER_USERNAME --email $DJANGO_SUPERUSER_EMAIL

# Start the server using the config file
exec python -m gunicorn -c gunicorn.conf.py chavi_client.wsgi:application
