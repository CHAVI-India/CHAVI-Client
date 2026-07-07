#!/bin/bash
set -e

echo "========================================="
echo "MIGRATION REPAIR TOOL"
echo "========================================="
echo ""
echo "⚠ WARNING: This script will modify your database migration state!"
echo ""
echo "This script will:"
echo "  1. Detect migration inconsistencies"
echo "  2. Attempt automatic repair"
echo "  3. Reapply migrations if needed"
echo ""
read -p "Do you want to continue? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "Starting repair process..."
echo ""

# Function to check if a table exists
table_exists() {
    python manage.py dbshell <<EOF 2>/dev/null | grep -q "$1"
SELECT tablename FROM pg_tables WHERE tablename = '$1';
EOF
    return $?
}

# Function to count data_import tables
count_data_import_tables() {
    python manage.py dbshell <<EOF 2>/dev/null | grep -oE '[0-9]+' | head -1
SELECT COUNT(*) FROM pg_tables WHERE tablename LIKE 'data_import_%';
EOF
}

# Function to check if migration is not applied
migration_not_applied() {
    python manage.py showmigrations "$1" 2>&1 | grep -q "\[ \].*$2"
    return $?
}

# Function to check if migration is applied
migration_applied() {
    python manage.py showmigrations "$1" 2>&1 | grep -q "\[X\].*$2"
    return $?
}

echo "Step 1: Analyzing current state..."
echo "----------------------------------------"

TABLE_COUNT=$(count_data_import_tables)
echo "Found $TABLE_COUNT data_import table(s) in database"

# Scenario 1: Migration not recorded but tables exist
if migration_not_applied "data_import" "0001_initial" && [ "$TABLE_COUNT" -gt 0 ]; then
    echo "✓ Detected: $TABLE_COUNT table(s) exist but 0001_initial not recorded"
    echo "  → Applying fix: Fake-apply 0001_initial"
    
    if python manage.py migrate data_import 0001_initial --fake; then
        echo "  ✓ Successfully fake-applied 0001_initial"
    else
        echo "  ✗ Failed to fake-apply 0001_initial"
        exit 1
    fi

# Scenario 2: Migration recorded but tables don't exist
elif migration_applied "data_import" "0001_initial" && [ "$TABLE_COUNT" -eq 0 ]; then
    echo "✓ Detected: Migration recorded but NO tables exist"
    echo "  → Applying fix: Reset and reapply migrations"
    
    echo "  → Removing fake migration records..."
    if python manage.py migrate data_import zero --fake; then
        echo "    ✓ Migration records removed"
    else
        echo "    ✗ Failed to remove migration records"
        exit 1
    fi
    
    echo "  → Applying migrations properly..."
    if python manage.py migrate data_import; then
        echo "    ✓ Migrations applied successfully"
    else
        echo "    ✗ Failed to apply migrations"
        exit 1
    fi

# Scenario 3: Migration recorded but partial tables (incomplete state)
elif migration_applied "data_import" "0001_initial" && [ "$TABLE_COUNT" -gt 0 ] && [ "$TABLE_COUNT" -lt 11 ]; then
    echo "⚠ Detected: Migration recorded but only $TABLE_COUNT table(s) exist (expected 11-12)"
    echo "  → Applying fix: Reset and reapply migrations"
    
    echo "  → Removing migration records..."
    if python manage.py migrate data_import zero --fake; then
        echo "    ✓ Migration records removed"
    else
        echo "    ✗ Failed to remove migration records"
        exit 1
    fi
    
    echo "  → Applying migrations properly..."
    if python manage.py migrate data_import; then
        echo "    ✓ Migrations applied successfully"
    else
        echo "    ✗ Failed to apply migrations"
        exit 1
    fi

# Scenario 4: Both not applied and tables don't exist (normal state)
elif migration_not_applied "data_import" "0001_initial" && [ "$TABLE_COUNT" -eq 0 ]; then
    echo "✓ Detected: Fresh state (no migrations, no tables)"
    echo "  → Applying migrations normally..."
    
    if python manage.py migrate data_import; then
        echo "  ✓ Migrations applied successfully"
    else
        echo "  ✗ Failed to apply migrations"
        exit 1
    fi

# Scenario 5: Everything looks good
else
    echo "✓ No obvious issues detected with 0001_initial"
    echo "  Migration state appears consistent ($TABLE_COUNT tables)"
fi

echo ""
echo "Step 2: Applying any remaining migrations..."
echo "----------------------------------------"

if python manage.py migrate --noinput; then
    echo "✓ All migrations applied successfully"
else
    echo "✗ Some migrations failed"
    echo ""
    echo "Please check the error messages above and:"
    echo "  1. Review migration dependencies"
    echo "  2. Check for syntax errors in migration files"
    echo "  3. Verify database permissions"
    exit 1
fi

echo ""
echo "Step 3: Verifying final state..."
echo "----------------------------------------"
python manage.py showmigrations data_import

echo ""
echo "========================================="
echo "REPAIR COMPLETE"
echo "========================================="
echo "✓ Migration state has been repaired"
echo ""
echo "Next steps:"
echo "  1. Restart your application"
echo "  2. Verify functionality"
echo "  3. Check application logs for any issues"
echo "========================================="
