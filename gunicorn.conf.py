import os

# Server socket
bind = "0.0.0.0:8000"
backlog = 2048

# Worker processes — the web tier is I/O-bound (database calls, progress
# polling), so a small number of preloaded workers is plenty. Do NOT scale
# this off the CPU count: each worker loads a full copy of the Django app
# into RAM, and 2*cores+1 workers on a shared host permanently occupies
# several GB of RAM while competing with the Celery workers for the same
# cores. Override via WEB_CONCURRENCY for larger or dedicated hosts.
workers = int(os.environ.get('WEB_CONCURRENCY', '4'))
worker_class = 'gthread'  # Threaded workers for I/O-bound tasks
threads = 2  # Concurrent requests per worker

# A stuck request should not hold a worker for hours — recycle aggressively
# instead. (Long-running work belongs in Celery, not the web request.)
timeout = 30
keepalive = 5
graceful_timeout = 30
max_requests = 1000  # Recycle workers periodically to prevent memory leaks
max_requests_jitter = 50  # Random jitter to avoid all workers recycling at once

# Logging
accesslog = '/app/logs/gunicorn-access.log'
errorlog = '/app/logs/gunicorn-error.log'
loglevel = 'info'

# Process naming
proc_name = 'chaviclient'

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# Performance tuning
preload_app = True  # With a small worker count, preloading saves RAM
worker_tmp_dir = '/dev/shm'  # Use shared memory for temporary files (faster I/O)
limit_request_line = 8190  # Increased request line limit
limit_request_fields = 200  # Increased header fields limit
limit_request_field_size = 8190  # Increased header field size limit

# SSL
keyfile = None
certfile = None

# Server hooks
def on_starting(server):
    # Ensure log directory exists
    os.makedirs('/app/logs', exist_ok=True)

def on_reload(server):
    pass

def on_exit(server):
    pass
