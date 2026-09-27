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
| chaviclient-dicom | Inbound DICOM server (C-ECHO/C-STORE/C-FIND SCP on port 11112) |
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

### GPU Acceleration (Optional)

Lookup-table embeddings (semantic search) are computed by the Celery worker and
auto-detect a usable NVIDIA GPU — no configuration is needed beyond granting
the container GPU access. Without it, computation runs on CPU.

Host prerequisites:

- NVIDIA driver recent enough for the bundled CUDA build (torch cu130)
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- A GPU with compute capability ≥ sm_75 (Turing or newer, ~2018+); unsupported
  GPUs are detected and automatically skipped in favour of CPU

Then uncomment the `deploy.resources.reservations.devices` block on
`chaviclient-celery-worker` in `docker-compose.yml` and restart:

```bash
docker compose up -d
```

Verify the worker sees the GPU:

```bash
docker exec chaviclient-celery-worker python -c "import torch; print(torch.cuda.is_available())"
```

The worker log records the resolved device when the embedding model loads.
Note that each prefork child loads its own model copy — with
`--concurrency=2`, VRAM usage is roughly 2× the model size, so lower the
concurrency for large models on small GPUs.

Only the worker computes embeddings — the web container dispatches tasks and
never loads the model, so it needs no GPU grant. If you run the embedding
management command manually, run it inside the worker container to get GPU:

```bash
docker exec chaviclient-celery-worker python manage.py compute_lookup_embeddings --refresh
```

### Shared Media Volume

The `./media` directory is shared between the Django and Celery worker containers. This ensures that files uploaded through the Django app are accessible to Celery workers for processing, and that generated export files are accessible to Django for download.

### Logs

All app containers mount `./logs` at `/app/logs`, so `debug.log`,
`dicom_server.log`, `dicom_import.log` and `deidentification.log` are readable
directly on the Docker host. Log lines are prefixed with the container
hostname, which identifies which container wrote each line of the shared
files.

### Task Results

Celery task results are stored in the Django database via `django-celery-results`. You can view task results and download generated files from the Django admin under **Task Results**.

### DICOM Server

The `chaviclient-dicom` container runs the inbound DICOM service (`python -m dicom_server`): a C-ECHO/C-STORE/C-FIND SCP that receives studies into the app. Received files land in the shared `./media` volume under `processed_dicom/` and update the same patient/study tables as the web uploads. Outbound Query/Retrieve to remote PACS runs elsewhere — see *Query/Retrieve networking* below.

- **Port:** DICOM peers connect to port `11112` (published in the compose file). The listen port is configured in the database — keep the published port in sync if you change it.
- **Configuration:** all DICOM settings are database-backed (no env vars). Staff users edit them under **Data Import → DICOM Server** in the web UI: server AE title/port/enable at `/dicom-server/config/`, remote PACS nodes at `/dicom-server/nodes/`. Restart the container after changing AE title, bind address, or port: `docker compose restart chaviclient-dicom`.
- **Patient allow-list:** only instances whose `PatientID` matches an existing patient record are stored; unknown patients are rejected.
- **Retrieval:** query/retrieve jobs are dispatched to the Celery worker (no extra setup needed). Use **prefer C-GET** on a remote node when the remote cannot connect back to this server (e.g. behind NAT); C-MOVE requires the remote to reach this host on the configured port.

#### Query/Retrieve networking

Q/R traffic is split across three containers — knowing which one initiates each
connection makes firewall and PACS-side setup straightforward:

| Container | DICOM role |
| ------ | ------ |
| `chaviclient-celery-worker` | **Outbound Q/R SCU.** Retrieval jobs (manual `/dicom-server/retrieve/` and scheduled auto-retrieval) open TCP associations from here to each remote node's `host:port` — C-ECHO, C-FIND, C-MOVE and C-GET. |
| `chaviclient-django` | Runs the **C-ECHO test button** on `/dicom-server/nodes/` synchronously — another outbound SCU source. |
| `chaviclient-dicom` | **Inbound SCP only.** Receives C-STORE deliveries on the published port `11112` (direct pushes from modalities/PACS and C-MOVE sub-operations). |
| `chaviclient-celery-beat` | Schedules auto-retrieval tasks via RabbitMQ; opens no DICOM connections itself. |

**Outbound SCU connections originate from `chaviclient-django` and
`chaviclient-celery-worker`** — `chaviclient-dicom` never dials out, so it needs
no name-resolution setup. Docker NAT handles outbound traffic, but `node.host`
must resolve *inside each SCU container*. A LAN IP or public FQDN works as-is;
a bare hostname that DNS cannot resolve must be pinned with `extra_hosts` on
**both** SCU services:

```yaml
services:
  chaviclient-django:
    extra_hosts:
      - "siemenspacs:192.168.1.50"
  chaviclient-celery-worker:
    extra_hosts:
      - "siemenspacs:192.168.1.50"
```

Apply with `docker compose up -d` — `docker compose restart` does **not**
recreate containers, so `extra_hosts` edits have no effect until the next
`up -d`. Verify resolution inside each SCU container:

```bash
docker exec chaviclient-django        getent hosts siemenspacs
docker exec chaviclient-celery-worker getent hosts siemenspacs
```

The remote must also accept our calling AE title (`CHAVI_CLIENT` by default) —
many PACS and workstations whitelist calling AETs, and the *called* AET must
match the peer's configured DICOM AE title (often not its machine hostname).

**Inbound connectivity is only needed for C-MOVE.** The remote opens a *new*
connection back to our AE title, resolved on the PACS side to the Docker host's
IP and published port `11112`. C-GET (`prefer_c_get` on the node) instead
receives instances over the same association the worker opened, so it works
even when the Docker host is behind NAT — provided the remote supports C-GET.

| Remote node location | C-ECHO / C-FIND | C-MOVE | C-GET |
| ------ | ------ | ------ | ------ |
| Same LAN/site | Works | Works if the PACS routes our AE title → Docker host IP:11112 and the host firewall allows inbound 11112 | Works |
| Remote over internet/VPN, host behind NAT | Works if the remote address is routable | Fails unless the site router port-forwards to host:11112 | **Recommended** |
| Same Docker host | Set `node.host` to the host LAN IP — `localhost` inside a container means the container itself | Same as LAN | Works |

Notes:

- A failed C-MOVE return path does **not** raise an error in the request — the
  job completes with failed sub-operation counts. Check the RetrievalJob detail
  page and the `InboundDICOMInstance` audit rows in Django admin.
- `bind_address` must stay `0.0.0.0` so the SCP accepts connections forwarded by
  Docker. Changing the configured listen port requires editing the compose port
  mapping and re-creating the container.
- The **storage enabled** checkbox at `/dicom-server/config/` gates all inbound
  storage, including C-GET deliveries.
- If a remote node ever runs on the Docker host itself and you prefer the name
  `host.docker.internal`, add `extra_hosts: ["host.docker.internal:host-gateway"]`
  to the worker and web services (Docker Desktop resolves it automatically;
  needed on Linux only). Using the host's LAN IP works without it.

Quick checks:

```bash
# SCP listener reachable through the published port
nc -zv <docker-host-ip> 11112
docker exec chaviclient-dicom python -c "import socket; socket.create_connection(('127.0.0.1', 11112), 3)"

# Outbound reachability from the worker (Q/R SCU container)
docker exec chaviclient-celery-worker python -c "import socket; socket.create_connection(('<remote-host>', <remote-port>), 5)"
```
