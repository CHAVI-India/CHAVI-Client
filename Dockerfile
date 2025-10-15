# Stage 1: Base build stage
FROM python:3.13-slim-bookworm AS builder
 
# Create the app directory
RUN mkdir /app
 
# Set the working directory
WORKDIR /app

# Set environment variables to optimize Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1 

# Install dependencies first for caching benefit
COPY requirements.txt /app/ 
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt
 
# Stage 2: Production stage
FROM python:3.13-slim-bookworm
 
RUN useradd -m -r appuser && \
   mkdir /app && \
   chown -R appuser /app

# Copy the Python dependencies from the builder stage
COPY --from=builder /install /usr/local
 
# Set the working directory
WORKDIR /app
 
# Copy application code and config files
COPY --chown=appuser:appuser . .
COPY --chown=appuser:appuser gunicorn.conf.py /app/gunicorn.conf.py
 
# Set environment variables to optimize Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1 
 
# Make entry file executable (before switching user)
RUN chmod +x /app/entrypoint.docker.sh

# Switch to non-root user
USER appuser

# Expose the application port
EXPOSE 8000
 
# Start the application using the entrypoint script
CMD ["/app/entrypoint.docker.sh"]