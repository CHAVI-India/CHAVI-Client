import multiprocessing
import os

# Server socket
bind = "0.0.0.0:8000"
backlog = 2048

# Worker processes
workers = 3
worker_class = 'gthread'
threads = 3
worker_connections = 1000
timeout = 3600
keepalive = 3600

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