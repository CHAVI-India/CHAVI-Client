# Migration Issue - Root Cause and Fix Summary

## Problem Discovered

**Error**: `DuplicateTable: relation "data_import_fileimportsession" already exists`

## Root Cause Analysis

### What We Found:
1. **No `data_import_*` tables exist** in the database
2. **Migration records for `0002` and `0003` exist** in `django_migrations` table (rows 117, 118)
3. **Migration record for `0001_initial` is missing** (row 116 was never created)
4. **Row 116 gap** caused by PostgreSQL sequence allocation during failed transaction rollback

### How This Happened:

The `entrypoint.docker.sh` had dangerous recovery logic:

```bash
# Line 35: This removed all migration records
python manage.py migrate data_import zero --fake 2>&1 || true

# Line 38: This tried to reapply
if python manage.py migrate data_import 2>&1; then
```

**Sequence of events**:
1. Initial deployment created tables and migrations successfully
2. Container restart triggered migration check failure
3. Recovery logic ran: `migrate zero --fake` (deleted all `data_import` migration records)
4. Attempted to reapply migrations
5. `0001_initial` failed (DuplicateTable at that time)
6. Transaction rolled back, ID 116 consumed but no row created
7. `0002` and `0003` were fake-applied (created records but no tables)
8. Later, someone dropped the database volume or tables manually
9. Now: migration records exist but no tables

### Why `--fake` Is Dangerous:

The `--fake` flag creates a mismatch between:
- **Django's belief** (migration records in database)
- **Reality** (actual database schema)

This leads to:
- DuplicateTable errors when tables exist but migrations aren't recorded
- Missing table errors when migrations are recorded but tables don't exist
- Inconsistent application state

## Changes Made

### 1. Simplified `entrypoint.docker.sh`

**Before**: Complex recovery logic with `--fake` flags that created inconsistent states

**After**: Simple, predictable migration handling:
```bash
# Run migrations
if ! python manage.py migrate --noinput; then
    echo "ERROR: Migration failed!"
    # Provide helpful diagnostic commands
    exit 1
fi
```

**Benefits**:
- ✅ Predictable behavior
- ✅ Fail fast with clear errors
- ✅ No automatic `--fake` operations
- ✅ Helpful error messages with next steps

### 2. Created Diagnostic Script

**File**: `scripts/diagnose-migrations.sh`

**Purpose**: Analyze migration state and detect inconsistencies

**Features**:
- Compares Django migration records vs actual database tables
- Detects common issues (tables exist but migrations not recorded, etc.)
- Checks for gaps in migration chain
- Provides clear recommendations

**Usage**:
```bash
docker exec -it chaviclient-django bash /app/scripts/diagnose-migrations.sh
```

### 3. Created Repair Script

**File**: `scripts/repair-migrations.sh`

**Purpose**: Automatically fix common migration inconsistencies

**Features**:
- Detects and fixes 4 common scenarios
- Interactive confirmation before making changes
- Safe handling of edge cases
- Verification after repair

**Usage**:
```bash
docker exec -it chaviclient-django bash /app/scripts/repair-migrations.sh
```

### 4. Updated Dockerfile

Added script permissions during build:
```dockerfile
RUN chmod +x /app/entrypoint.docker.sh && \
    chmod +x /app/scripts/diagnose-migrations.sh && \
    chmod +x /app/scripts/repair-migrations.sh
```

### 5. Created Documentation

**File**: `scripts/README.md`

Contains:
- Script usage instructions
- Common issues and solutions
- Manual migration commands
- Best practices
- Troubleshooting guide

## Immediate Fix for Current Issue

Since no `data_import_*` tables exist but migration records for `0002` and `0003` exist:

```bash
# Option 1: Use the repair script (recommended)
docker exec -it chaviclient-django bash /app/scripts/repair-migrations.sh

# Option 2: Manual fix
docker exec -it chaviclient-django python manage.py migrate data_import zero --fake
docker exec -it chaviclient-django python manage.py migrate data_import
docker exec -it chaviclient-django python manage.py migrate
```

## Prevention

The new entrypoint script prevents this by:
1. **No automatic `--fake` operations** - These should only be manual
2. **Fail fast** - Stop immediately on migration errors
3. **Clear guidance** - Tell users exactly what to do
4. **Separate repair tools** - Manual intervention when needed

## Best Practices Going Forward

1. ✅ **Never use `--fake` in automated scripts**
2. ✅ **Always diagnose before repairing**
3. ✅ **Keep database backups**
4. ✅ **Test in development first**
5. ✅ **Use the diagnostic script when issues occur**
6. ✅ **Understand what repair scripts do before running them**

## Files Modified

- ✏️ `entrypoint.docker.sh` - Simplified migration logic
- ✏️ `Dockerfile` - Added script permissions
- ➕ `scripts/diagnose-migrations.sh` - New diagnostic tool
- ➕ `scripts/repair-migrations.sh` - New repair tool
- ➕ `scripts/README.md` - Documentation

## Next Steps

1. **Rebuild the Docker image** to include the changes:
   ```bash
   docker-compose build
   ```

2. **Fix the current migration issue**:
   ```bash
   docker exec -it chaviclient-django bash /app/scripts/repair-migrations.sh
   ```

3. **Restart the application**:
   ```bash
   docker-compose restart chaviclient-django
   ```

4. **Verify everything works**:
   ```bash
   docker exec -it chaviclient-django python manage.py showmigrations data_import
   ```

## Questions?

Refer to `scripts/README.md` for detailed usage instructions and troubleshooting.
