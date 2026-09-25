# ==============================================================================
# DEPRECATED: LEGACY MONOLITHIC DEPLOYMENT IMAGE
# ==============================================================================
# 
# WARNING: This Dockerfile represents the WP-1 prototype architecture where
# the Edge Inference and Central Backend were merged into a single container.
#
# DO NOT USE THIS FOR PRODUCTION.
#
# Production deployments MUST use the isolated edge-to-cloud topology:
# - Edge Container:   edge/Dockerfile
# - Central Backend:  backend/Dockerfile
#
# This file is retained ONLY as a compatibility wrapper for legacy CI scripts
# and local Render-style single-container preview deployments.
#
# ==============================================================================

# --- Stage 1: build the frontend ---
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN ["npm", "ci"]
COPY frontend/ ./
ARG VITE_BACKEND_URL
ENV VITE_BACKEND_URL=$VITE_BACKEND_URL
RUN ["npm", "run", "build"]

# --- Stage 2: the actual runtime image ---
FROM python:3.12-slim AS runtime
WORKDIR /app

# Install system dependencies required for OpenCV and other edge ML libraries
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install full requirements since the container runs both edge and backend for the prototype demo
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY shared/ ./shared/
COPY edge/ ./edge/
COPY demo/ ./demo/
COPY certs/ ./certs/
COPY scripts/ ./scripts/
COPY yolov8n.pt ./
COPY start.sh ./
RUN chmod +x start.sh

COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Ensure the data directories exist for the Render Disk mount
RUN mkdir -p /app/edge/data /app/demo/videos

ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8443
EXPOSE 8443

CMD ["./start.sh"]
