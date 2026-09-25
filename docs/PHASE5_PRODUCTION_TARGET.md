# Phase 5: Production Target Design

## Architecture

**STATUS:** DESIGNED / NOT DEPLOYED / NOT VALIDATED

### Edge Compute Tier
- **Hardware:** Physical x86/ARM devices (e.g. NVIDIA Jetson, Intel NUCs) running standalone container instances.
- **Network Segmentation:** Edges reside on isolated CCTV VLANs (no inbound internet access). All outbound communication routes exclusively over mTLS Port 443 to the Central API.
- **Local Persistence:** Edge SQLite databases and rotating NVMe drives for local queue/evidence buffering.

### Central Infrastructure
- **Ingress:** Nginx/Traefik terminating mTLS and routing strictly authenticated payloads to the internal FastAPI cluster.
- **State:** High-Availability PostgreSQL Cluster (e.g. Supabase/Patroni) handling relational tracking data.
- **Storage:** Private S3/MinIO clustered object storage bucket for raw evidence binaries, secured by STS or IAM roles. No public read access.
- **Observability:** Centralized Prometheus scraping backend metrics, and Loki aggregating edge logs. Grafana sits behind SSO/RBAC.

### Cryptography & Trust
- Evidence keys (`CameraKey`) rotated mechanically. Edge nodes hold independent `Ed25519` private keys used solely for payload validation.
