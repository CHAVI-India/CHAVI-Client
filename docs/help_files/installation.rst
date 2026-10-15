Installation Guide
=================

This guide will help you install and set up the Django project on your system for local network (LAN) access.

Prerequisites
------------

Before installation, ensure you have the following:

* Python 3.8 or higher
* pip (Python package installer)
* Git (for version control)

Environment Setup
---------------

1. Copy the sample environment file::

    cp sampleenv .env

2. Update the .env file with your settings:

   * ``SECRET_KEY`` - Django secret key for security (change this for production!)
   * ``DEBUG`` - Set to True for development, False for production
   * ``DJANGO_ALLOWED_HOSTS`` - Comma-separated list of allowed hostnames/IPs
   * ``DJANGO_DB_ENGINE`` - Database engine (default: django.db.backends.postgresql)
   * ``DJANGO_DB_NAME`` - Name of your database
   * ``DJANGO_DB_USER`` - Database username
   * ``DJANGO_DB_PASSWORD`` - Database password
   * ``DJANGO_DB_HOST`` - Database host address
   * ``DJANGO_DB_PORT`` - Database port number

   Example .env file::

    SECRET_KEY=django-insecure-%zvbz3$uzi$kvpd$2@5+6-=@7&8%l4^-lp!$(s#ysd9w8)fe!
    DEBUG=True
    DJANGO_ALLOWED_HOSTS='127.0.0.1,localhost'
    
    DJANGO_DB_ENGINE=django.db.backends.postgresql
    DJANGO_DB_NAME=chaviclient
    DJANGO_DB_USER=postgres
    DJANGO_DB_PASSWORD=your_secure_password
    DJANGO_DB_HOST=localhost
    DJANGO_DB_PORT=5432

   Note: Make sure to change the SECRET_KEY and set a secure database password before deployment.

3. Database Setup:
   
   For PostgreSQL database (recommended):
   
   * Install PostgreSQL::

        # On Linux
        sudo apt install postgresql postgresql-contrib
        
        # On Windows
        # Download and install from https://www.postgresql.org/download/windows/

   * Create database::

        # Login to PostgreSQL
        sudo -u postgres psql
        
        # Create database
        CREATE DATABASE chaviclient;
        
        # Create user (if needed)
        CREATE USER your_user WITH PASSWORD 'your_password';
        
        # Grant privileges
        GRANT ALL PRIVILEGES ON DATABASE chaviclient TO your_user;

Linux Installation
----------------

1. Update your system packages::

    sudo apt update
    sudo apt upgrade

2. Install Python and required system packages::

    sudo apt install python3 python3-pip python3-venv

3. Clone the repository::

    git clone <repository-url>
    cd <project-directory>

4. Create and activate a virtual environment::

    python3 -m venv venv
    source venv/bin/activate

5. Install required Python packages::

    pip install -r requirements.txt

6. Set up the database::

    python manage.py migrate

7. Create a superuser account::

    python manage.py createsuperuser

8. Collect static files::

    python manage.py collectstatic

9. Run the development server for LAN access::

    python manage.py runserver 0.0.0.0:8000

Windows Installation
------------------

1. Download and install Python:
   
   * Visit https://www.python.org/downloads/
   * Download the latest Python version
   * Run the installer (make sure to check "Add Python to PATH")

2. Download and install Git:
   
   * Visit https://git-scm.com/download/win
   * Download and run the installer

3. Clone the repository:

   Open Command Prompt and run::

    git clone <repository-url>
    cd <project-directory>

4. Create and activate a virtual environment::

    python -m venv venv
    venv\Scripts\activate

5. Install required Python packages::

    pip install -r requirements.txt

6. Set up the database::

    python manage.py migrate

7. Create a superuser account::

    python manage.py createsuperuser

8. Collect static files::

    python manage.py collectstatic

9. Run the development server for LAN access::

    python manage.py runserver 0.0.0.0:8000

Running the Celery Workers
-------------------------

Background jobs — de-identification, DICOM retrieval, ZIP and clinical data
downloads, and scheduled maintenance tasks — are processed by Celery
workers, not by the web server. Start them before using those features;
jobs started without a worker simply wait in the queue.

Two workers are needed, and each must have a **distinct node name** (the
``-n`` option). If two workers share the same name, the second one crashes
at startup with ``RESOURCE_LOCKED`` on the ``...celery.pidbox`` queue — that
queue is exclusive to the worker name, so the first worker still holds it::

    celery -A chavi_client worker -l info -n general@%h -Q default -c 2
    celery -A chavi_client worker -l info -n deid@%h -Q deid -c 1

* ``general@%h`` — general tasks (retrieval, ZIP/clinical downloads,
  scheduled jobs), two slots, ``default`` queue.
* ``deid@%h`` — de-identification only, **one slot**, dedicated ``deid``
  queue, so de-identification batches run strictly one after another with a
  single copy of the text-detection models in memory.

A de-identification job started while another is running waits in the
queue; its task run shows no progress until the running batch finishes.
Do not run the deid worker with ``-c 2`` (or add ``deid`` to the general
worker's queues) — parallel de-identification batches load duplicate model
stacks, which is exactly what the single-slot worker exists to prevent.

(When running under Docker instead, both workers ship as containers in
``example_docker-compose.yml`` with distinct container hostnames, so no
``-n`` is needed there — see the :doc:`docker_installation` page.)

Accessing the Application
-----------------------

After starting the server, the application will be available at:

* Local access: http://localhost:8000
* LAN access: http://<your-ip-address>:8000

To find your IP address:

* On Linux: Run ``ip addr`` or ``ifconfig``
* On Windows: Run ``ipconfig`` in Command Prompt


For additional help, contact the CHAVI team.
