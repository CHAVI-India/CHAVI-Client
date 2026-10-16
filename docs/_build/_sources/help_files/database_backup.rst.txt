Database Backup and Restore
==============================

This guide describes how to backup and restore the PostgreSQL database used by the CHAVI client in a Dockerized environment.

Overview
--------
- The database runs in a dedicated container named ``chaviclient-database`` (see ``docker_install/example_docker-compose.yml``).
- Database credentials are set in the ``.env`` file referenced by docker-compose.
- Backups should be stored in a persistent directory on the host (e.g. ``/mnt/share/chavi_client/backups``).

.. note::
   Always ensure your backup directory is writable by the user running the backup script.

Relevant Environment Variables
---------------------------------
Check your ``.env`` file for these variables, which are used in both backup and restore commands:

.. code-block:: bash

   POSTGRES_DB=your_db_name
   POSTGRES_USER=your_db_user
   POSTGRES_PASSWORD=your_db_password

Backup the Database
-------------------

1. **Create a backup directory (if not already present):**

   .. code-block:: bash

      mkdir -p /mnt/share/chavi_client/backups

2. **Create a backup script (e.g. ``backup.sh``):**

   .. code-block:: bash

      #!/bin/bash
      BACKUP_DIR=/mnt/share/chavi_client/backups
      DB_NAME=your_db_name        # Set from POSTGRES_DB in .env
      DB_USER=your_db_user        # Set from POSTGRES_USER in .env
      CONTAINER_NAME=chaviclient-database
      TIMESTAMP=$(date +"%F_%H-%M-%S")
      BACKUP_FILE="$BACKUP_DIR/backup_${DB_NAME}_$TIMESTAMP.sql"
      docker exec -t $CONTAINER_NAME pg_dump -U $DB_USER $DB_NAME > "$BACKUP_FILE"
      echo "Backup completed: $BACKUP_FILE"

   Replace ``your_db_name`` and ``your_db_user`` with the actual values from your ``.env`` file.

3. **Make the script executable:**

   .. code-block:: bash

      chmod +x backup.sh

4. **Run the backup script:**

   .. code-block:: bash

      ./backup.sh

Automating Backups
------------------
You can automate backups with a cron job (Linux/macOS) or Task Scheduler (Windows).

Restore the Database
--------------------
To restore a backup, use the following steps:

1. **Copy your backup file to the host if needed.**
2. **Run the restore command:**

   .. code-block:: bash

      BACKUP_FILE=/mnt/share/chavi_client/backups/backup_your_db_name_YYYY-MM-DD_HH-MM-SS.sql
      DB_NAME=your_db_name        # Set from POSTGRES_DB in .env
      DB_USER=your_db_user        # Set from POSTGRES_USER in .env
      CONTAINER_NAME=chaviclient-database
      cat $BACKUP_FILE | docker exec -i $CONTAINER_NAME psql -U $DB_USER $DB_NAME

   Replace ``your_db_name`` and the backup filename as appropriate.

.. note::
   The container name (``chaviclient-database``) must match the name in your ``docker-compose.yml``. If you change it, update the scripts accordingly.

Troubleshooting
---------------
- Ensure the database container is running before performing backup or restore.
- Check permissions on the backup directory.
- Use ``docker ps`` to verify container names.







