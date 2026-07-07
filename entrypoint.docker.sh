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
if ! python manage.py migrate --noinput 2>&1; then
    echo "========================================="
    echo "⚠ WARNING: Migration failed!"
    echo "========================================="
    echo ""
    echo "Running diagnostic script..."
    echo ""
    
    # Run diagnostic script
    bash /app/scripts/diagnose-migrations.sh
    
    echo ""
    echo "========================================="
    echo "CONTAINER STAYING ALIVE FOR MANUAL REPAIR"
    echo "========================================="
    echo ""
    echo "The container will stay running so you can fix the issue."
    echo ""
    echo "To connect to the container:"
    echo "  docker exec -it chaviclient-django bash"
    echo ""
    echo "Then run the repair script:"
    echo "  bash /app/scripts/repair-migrations.sh"
    echo ""
    echo "Or fix manually using the diagnostic output above."
    echo ""
    echo "========================================="
    
    # Keep container alive for manual intervention
    tail -f /dev/null
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
