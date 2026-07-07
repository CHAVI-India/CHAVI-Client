#!/bin/bash
set -e

echo "========================================="
echo "MIGRATION DIAGNOSTIC TOOL"
echo "========================================="
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

# Function to check if migration is applied
migration_applied() {
    python manage.py showmigrations "$1" 2>&1 | grep -q "\[X\].*$2"
    return $?
}

# Function to check if migration is not applied
migration_not_applied() {
    python manage.py showmigrations "$1" 2>&1 | grep -q "\[ \].*$2"
    return $?
}

echo "1. Checking Django migration records..."
echo "----------------------------------------"
python manage.py showmigrations data_import
echo ""

echo "2. Checking actual database tables..."
echo "----------------------------------------"
python manage.py dbshell <<EOF 2>&1 | grep -E "data_import_|List of relations|No relations found"
\dt data_import_*
EOF
echo ""

echo "3. Checking migration records in database..."
echo "----------------------------------------"
python manage.py dbshell <<EOF 2>&1
SELECT id, name, applied 
FROM django_migrations 
WHERE app='data_import' 
ORDER BY id;
EOF
echo ""

echo "4. Analyzing inconsistencies..."
echo "----------------------------------------"

ISSUES_FOUND=0
TABLE_COUNT=$(count_data_import_tables)

# 0001_initial creates 11 tables, so we check if any tables exist
# Note: There's also a ManyToMany table for project_name, so total could be 12
if migration_not_applied "data_import" "0001_initial"; then
    echo "⚠ Issue detected: 0001_initial is NOT applied"
    
    if [ "$TABLE_COUNT" -gt 0 ]; then
        echo "  ✗ CRITICAL: Found $TABLE_COUNT data_import table(s) but migration not recorded!"
        echo "  → This causes DuplicateTable errors"
        echo "  → Fix: Run repair script to fake-apply 0001_initial"
        ISSUES_FOUND=$((ISSUES_FOUND + 1))
    else
        echo "  ℹ No data_import tables exist - this is normal for fresh install"
        echo "  → Just run: python manage.py migrate"
    fi
elif migration_applied "data_import" "0001_initial"; then
    echo "✓ 0001_initial is applied"
    
    # 0001_initial should create 11-12 tables
    if [ "$TABLE_COUNT" -eq 0 ]; then
        echo "  ✗ CRITICAL: Migration recorded but NO tables exist!"
        echo "  → This indicates fake-applied migrations"
        echo "  → Fix: Run repair script to reset and reapply"
        ISSUES_FOUND=$((ISSUES_FOUND + 1))
    elif [ "$TABLE_COUNT" -lt 11 ]; then
        echo "  ⚠ WARNING: Only $TABLE_COUNT table(s) exist (expected 11-12)"
        echo "  → Partial migration or incomplete table creation"
        echo "  → Consider running repair script"
        ISSUES_FOUND=$((ISSUES_FOUND + 1))
    else
        echo "  ✓ Found $TABLE_COUNT table(s) - looks good"
    fi
fi

# Check for gaps in migration chain
echo ""
echo "5. Checking for migration chain gaps..."
echo "----------------------------------------"
python manage.py dbshell <<EOF 2>&1 | while read -r line; do
    echo "  $line"
done
SELECT 
    CASE 
        WHEN id - LAG(id) OVER (ORDER BY id) > 1 
        THEN '⚠ Gap detected at ID ' || id::text
        ELSE '✓ ID ' || id::text || ' - OK'
    END as status,
    name
FROM django_migrations 
WHERE app='data_import'
ORDER BY id;
EOF

echo ""
echo "========================================="
echo "DIAGNOSTIC SUMMARY"
echo "========================================="

if [ $ISSUES_FOUND -eq 0 ]; then
    echo "✓ No critical issues detected"
    echo ""
    echo "If migrations are still failing, check:"
    echo "  • Other app dependencies"
    echo "  • Database permissions"
    echo "  • Migration file syntax errors"
else
    echo "✗ Found $ISSUES_FOUND critical issue(s)"
    echo ""
    echo "To fix automatically, run:"
    echo "  bash /app/scripts/repair-migrations.sh"
    echo ""
    echo "Or fix manually by following the suggestions above."
fi
echo "========================================="
