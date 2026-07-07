# Migration Diagnostic and Repair Scripts

This directory contains tools to diagnose and fix Django migration issues in the dockerized environment.

## Scripts

### 1. `diagnose-migrations.sh`
**Purpose**: Analyze migration state and detect inconsistencies

**Usage**:
```bash
docker exec -it chaviclient-django bash /app/scripts/diagnose-migrations.sh
```

**What it checks**:
- Django migration records vs actual database tables
- Migration chain gaps
- Common inconsistencies (tables exist but migrations not recorded, or vice versa)

**When to use**:
- When migrations fail during deployment
- To understand the current migration state
- Before running repairs

---

### 2. `repair-migrations.sh`
**Purpose**: Automatically fix common migration inconsistencies

**Usage**:
```bash
docker exec -it chaviclient-django bash /app/scripts/repair-migrations.sh
```

**What it fixes**:
- **Scenario 1**: Tables exist but `0001_initial` not recorded → Fake-applies the migration
- **Scenario 2**: Migration recorded but tables don't exist → Resets and reapplies migrations
- **Scenario 3**: Fresh state → Applies migrations normally

**When to use**:
- After running `diagnose-migrations.sh` and confirming issues
- When you see `DuplicateTable` errors
- When migration state is inconsistent

**⚠ Warning**: This script modifies your database migration state. Always:
1. Run `diagnose-migrations.sh` first
2. Backup your database if it contains important data
3. Understand what the script will do before confirming

---

## Common Issues and Solutions

### Issue: `DuplicateTable: relation "data_import_fileimportsession" already exists`

**Diagnosis**:
```bash
docker exec -it chaviclient-django bash /app/scripts/diagnose-migrations.sh
```

**Fix**:
```bash
docker exec -it chaviclient-django bash /app/scripts/repair-migrations.sh
```

---

### Issue: Migration records exist but tables don't

**Diagnosis**:
```bash
docker exec -it chaviclient-django bash /app/scripts/diagnose-migrations.sh
```

**Fix**:
```bash
docker exec -it chaviclient-django bash /app/scripts/repair-migrations.sh
```

---

### Issue: Need to start completely fresh

**Solution**:
```bash
# Stop containers
docker-compose down

# Remove database volume
docker volume rm chavi_client_postgres_data

# Rebuild and start
docker-compose up --build
```

---

## Manual Migration Commands

If you prefer manual control:

### Check migration status
```bash
docker exec -it chaviclient-django python manage.py showmigrations data_import
```

### Fake-apply a migration (tables already exist)
```bash
docker exec -it chaviclient-django python manage.py migrate data_import 0001_initial --fake
```

### Reset migrations (remove records, keep tables)
```bash
docker exec -it chaviclient-django python manage.py migrate data_import zero --fake
```

### Apply migrations normally
```bash
docker exec -it chaviclient-django python manage.py migrate data_import
```

### Check database tables
```bash
docker exec -it chaviclient-database psql -U $POSTGRES_USER -d $POSTGRES_DB -c "\dt data_import_*"
```

---

## Understanding the Entrypoint Changes

The `entrypoint.docker.sh` has been simplified to:
- ✅ Run migrations normally
- ✅ Fail fast with clear error messages
- ❌ No automatic `--fake` recovery (too dangerous)
- ✅ Provide helpful diagnostic commands on failure

This makes deployments more predictable and prevents the script from creating inconsistent states.

---

## Best Practices

1. **Never use `--fake` in automated scripts** - It should only be used manually when you understand the implications
2. **Always diagnose before repairing** - Understand what's wrong before attempting fixes
3. **Keep database backups** - Especially before running repair scripts
4. **Test in development first** - Try fixes in a dev environment before production
5. **Check logs** - Migration errors often have helpful details in the logs

---

## Troubleshooting

If the repair script doesn't fix your issue:

1. Check the full error output from migrations
2. Verify database permissions
3. Check for syntax errors in migration files
4. Look for circular dependencies between apps
5. Consider manual intervention with Django shell

For complex issues, consult the Django migration documentation or seek expert help.
