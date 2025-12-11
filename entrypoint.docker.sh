#!/bin/bash
set -e  # Exit on error

echo "========================================="
echo "Starting Django Application Entrypoint"
echo "========================================="

# Wait for database to be ready
echo "[1/5] Waiting for database connection..."
MAX_RETRIES=30
RETRY_COUNT=0

until python manage.py check --database default > /dev/null 2>&1; do
  RETRY_COUNT=$((RETRY_COUNT + 1))
  if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
    echo "ERROR: Database connection failed after $MAX_RETRIES attempts"
    exit 1
  fi
  echo "Database unavailable - waiting... (attempt $RETRY_COUNT/$MAX_RETRIES)"
  sleep 2
done
echo "✓ Database is ready!"

# Run migrations with error handling
echo "[2/5] Running database migrations..."
if ! python manage.py migrate --noinput 2>&1; then
    echo "⚠ WARNING: Migration failed! Attempting to fix..."
    
    # Check if it's a data_import migration issue
    if python manage.py showmigrations data_import 2>&1 | grep -q "\[X\].*0001_initial"; then
        echo "Detected data_import migration inconsistency"
        echo "Attempting automatic recovery..."
        
        # Fake-unapply data_import migrations
        python manage.py migrate data_import zero --fake 2>&1 || true
        
        # Reapply data_import migrations
        if python manage.py migrate data_import 2>&1; then
            echo "✓ data_import migrations fixed"
            
            # Retry all migrations
            echo "Retrying all migrations..."
            if ! python manage.py migrate --noinput 2>&1; then
                echo "ERROR: Migration still failing after recovery attempt"
                exit 1
            fi
        else
            echo "ERROR: Could not fix data_import migrations"
            exit 1
        fi
    else
        echo "ERROR: Migration failed with unknown issue"
        exit 1
    fi
fi
echo "✓ Migrations completed successfully!"

# Collect static files
echo "[3/5] Collecting static files..."
python manage.py collectstatic --noinput
echo "✓ Static files collected!"

# Create superuser if it doesn't exist
echo "[4/5] Setting up superuser..."
if python manage.py createsuperuser --noinput --username "$DJANGO_SUPERUSER_USERNAME" --email "$DJANGO_SUPERUSER_EMAIL" 2>/dev/null; then
    echo "✓ Superuser created: $DJANGO_SUPERUSER_USERNAME"
else
    echo "✓ Superuser already exists"
fi

# Start the server using the config file
echo "[5/5] Starting Gunicorn server..."
echo "========================================="
exec python -m gunicorn -c gunicorn.conf.py chavi_client.wsgi:application
