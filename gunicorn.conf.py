import multiprocessing
import os

# Server socket
bind = "0.0.0.0:8000"
backlog = 2048

# Worker processes - optimized for long-running tasks
workers = multiprocessing.cpu_count() * 2 + 1  # Dynamic worker count based on CPU cores
worker_class = 'gthread'  # Use threaded workers for I/O bound tasks
threads = 4  # Increased thread count per worker
worker_connections = 1000
timeout = 7200  # 2 hours timeout for long-running requests
keepalive = 7200  # Keep connections alive for 2 hours
graceful_timeout = 300  # Time to gracefully shutdown workers
max_requests = 0  # Disable worker recycling to avoid interrupting long tasks
max_requests_jitter = 0  # No jitter since we disabled max_requests

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

# Performance tuning for long-running tasks
preload_app = True  # Preload application for better memory efficiency
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