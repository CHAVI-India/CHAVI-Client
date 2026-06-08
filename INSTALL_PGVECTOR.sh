#!/bin/bash
# Script to install pgvector extension for PostgreSQL

echo "Installing pgvector for PostgreSQL..."

# Install build dependencies
sudo apt-get update
sudo apt-get install -y postgresql-server-dev-14 build-essential git

# Clone and build pgvector
cd /tmp
git clone --branch v0.7.0 https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install

echo "pgvector installed successfully!"
echo ""
echo "Now restart PostgreSQL:"
echo "  sudo systemctl restart postgresql"
echo ""
echo "Then run migrations:"
echo "  python manage.py migrate"
