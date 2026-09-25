#!/bin/bash
# NETRAKSH - Unified startup script for Render deployment
# Starts the background Edge pipeline and the FastAPI backend.

echo "Bridging Render Secret Files to Edge Pipeline..."
mkdir -p /app/certs/edge
if [ -f "/etc/secrets/cam-border-01.key" ]; then
    cp -p /etc/secrets/cam-border-01.key /app/certs/edge/cam-border-01.key
else
    echo "ERROR: /etc/secrets/cam-border-01.key not found."
    echo "You must provide the Edge private key via Render Secret Files."
    exit 1
fi

echo "Starting Edge Pipeline in the background..."
# We run the demo runner which polls for /demo/scenario changes.
# This allows video uploads via the frontend to trigger an edge restart.
export BACKEND_URL="http://localhost:${PORT:-8443}"
python edge/demo_runner.py &

echo "Starting FastAPI Backend..."
# The port is supplied by Render via the $PORT environment variable.
uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8443}
