To do a docker based install, download the three files inside a folder and rename them as follows:

| Original File Name | Modified File name |
| ------ | ------ |
| example_docker-compose.yml | docker-compose.yml |
| example_.env | .env |
| example_nginx.conf | nginx.conf |

Ensure that Docker desktop is installed 

After that start the containers with the command 

```bash
docker compose up -d
```


## Containers

The Docker Compose setup includes the following containers:

| Container | Description |
| ------ | ------ |
| chaviclient-database | PostgreSQL 17 database |
| chaviclient-rabbitmq | RabbitMQ message broker with management UI (ports 5672 and 15672) |
| chaviclient-django | Django web application (Gunicorn) |
| chaviclient-celery-worker | Celery worker for asynchronous task processing |
| chaviclient-celery-beat | Celery beat scheduler for periodic tasks |
| chaviclient-proxy | Nginx reverse proxy |

### RabbitMQ Management UI

The RabbitMQ management UI is available at `http://localhost:15672`. Use the credentials defined in your `.env` file (`RABBITMQ_DEFAULT_USER` and `RABBITMQ_DEFAULT_PASS`).

### Celery Configuration

The following environment variables must be set in your `.env` file for Celery:

```
CELERY_BROKER_URL=amqp://chaviuser:chavipassword@chaviclient-rabbitmq:5672/chavi_vhost
RABBITMQ_DEFAULT_USER=chaviuser
RABBITMQ_DEFAULT_PASS=chavipassword
RABBITMQ_DEFAULT_VHOST=chavi_vhost
```

### Shared Media Volume

The `./media` directory is shared between the Django and Celery worker containers. This ensures that files uploaded through the Django app are accessible to Celery workers for processing, and that generated export files are accessible to Django for download.

### Task Results

Celery task results are stored in the Django database via `django-celery-results`. You can view task results and download generated files from the Django admin under **Task Results**.
