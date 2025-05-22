import multiprocessing
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('gunicorn.error')

# Server socket
bind = "0.0.0.0:8000"
backlog = 2048

# Worker processes
workers = 3
worker_class = 'gthread'
threads = 3
worker_connections = 1000
timeout = 300
keepalive = 65

# Logging
accesslog = '-'
errorlog = '-'
loglevel = 'debug'

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
    logger.debug("Server starting with config: %s", server.cfg)

def on_reload(server):
    logger.debug("Server reloading with config: %s", server.cfg)

def on_exit(server):
    logger.debug("Server exiting") 