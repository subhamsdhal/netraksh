# Phase 4 WP-4.2: Test Matrix

| ID | Test Case | Status | Objective |
|---|---|---|---|
| 1 | edge Dockerfile exists | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `edge/Dockerfile` is present. |
| 2 | backend Dockerfile exists | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `backend/Dockerfile` is present. |
| 3 | production edge entrypoint | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `edge/main.py` is the CMD, not `demo_runner.py`. |
| 4 | demo_runner is NOT production | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `demo_runner.py` is absent from CMD. |
| 5 | edge image private certs | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `COPY certs/` is absent in Edge image. |
| 6 | no hardcoded secrets | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `ENV SECRET_KEY=` etc are not in Dockerfiles. |
| 7 | non-root USER exists | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `USER netraksh` directive exists in images. |
| 8 | edge image Postgres dependency | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `libpq-dev` or similar is not in edge Dockerfile. |
| 9 | edge compose MinIO dependency | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `docker-compose.edge.yml` has no MinIO/DB services. |
| 10 | central compose services | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify backend, db, minio, frontend exist in central compose. |
| 11 | MinIO private exposure | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify MinIO requires credentials, no public anon access. |
| 12 | persistent edge volume | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `edge_data` volume is explicitly mounted. |
| 13 | bind-mount wholesale check | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `- ./:/app` is absent from production compose configurations. |
| 14 | health behavior configured | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify Compose `healthcheck` attributes on Postgres/MinIO. |
| 15 | shutdown behavior | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify containers support clean signals (SIGTERM). |
| 16 | deployment separation | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify separation of compose files and boundary docs. |
| 17 | mTLS config available | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify central compose supports mounting `/certs`. |
| 18 | rollback preserves edge data | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify edge local DB resides in `edge_data` volume. |
| 19 | root Dockerfile audited | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify legacy root Dockerfile is marked DEPRECATED. |
| 20 | required dependencies | NOT EXECUTED — ENVIRONMENT BLOCKED | Verify `edge/requirements.txt` contains required libraries. |
