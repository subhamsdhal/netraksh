FROM python:3.12-slim

WORKDIR /app

# Add non-root user
RUN groupadd -r netraksh && useradd -r -g netraksh netraksh

# Install OS dependencies if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements-backend.txt .
RUN pip install --no-cache-dir -r requirements-backend.txt

# Copy backend and shared folders
COPY backend/ /app/backend/
COPY shared/ /app/shared/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/alembic.ini
# Browser fallback for the bundled evaluator demo. Uploaded media uses the
# configured durable object store; this immutable asset is image content.
COPY demo/videos/uploaded_demo.mp4 /app/demo/videos/uploaded_demo.mp4

# TLS material is deployment-specific and must be mounted when mTLS/TLS is
# enabled.  Do not make the default image build depend on untracked secrets.
RUN mkdir -p /app/certs/ca /app/certs/server

# Set correct ownership for the non-root user
RUN chown -R netraksh:netraksh /app

USER netraksh

ENV PYTHONPATH=/app
ENV ENV=production

EXPOSE 8000

# Start exactly one backend/control-plane process. Render supplies PORT.
CMD ["sh", "-c", "python -m uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
