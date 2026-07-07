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

# Run migrations
echo "[2/5] Running database migrations..."
if ! python manage.py migrate --noinput; then
    echo "========================================="
    echo "ERROR: Migration failed!"
    echo "========================================="
    echo ""
    echo "This usually indicates:"
    echo "  • Database schema conflicts"
    echo "  • Inconsistent migration state"
    echo "  • Missing dependencies"
    echo ""
    echo "To diagnose the issue, run:"
    echo "  docker exec -it chaviclient-django python manage.py showmigrations"
    echo ""
    echo "For automated diagnosis and repair, run:"
    echo "  docker exec -it chaviclient-django bash /app/scripts/diagnose-migrations.sh"
    echo ""
    echo "For manual repair (use with caution):"
    echo "  docker exec -it chaviclient-django bash /app/scripts/repair-migrations.sh"
    echo "========================================="
    exit 1
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
