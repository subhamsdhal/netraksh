# NETRAKSH Test Harness

This repository contains a full Docker-based testing suite to validate the Edge Pipeline, Backend API, Evidence Chain, and Frontend without requiring host-machine dependency installations.

## Running the Tests
To execute the complete testing suite locally or in CI:

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

## What is Tested

1. **Edge Pipeline & Degradation (`tests/test_reliability_degradation.py`, `test_edge_pipeline.py`)**
   - Synthetically injects degraded frames (frozen video, fog, glare) into the `CameraHealthMonitor` and `SceneConditionClassifier` to ensure they accurately downgrade their state without crashing.
   - Validates the `HybridReliabilityEngine` math bounds (forces R into `[0.0, 1.0]`).

2. **Blockchain Tampering (`tests/test_hash_chain.py`)**
   - Injects mock evidence packages into the SQLite `EvidenceChainStore`.
   - Modifies the database directly via SQL injection to simulate an attacker altering historical evidence.
   - Asserts that `verify_chain()` catches the mismatch and correctly halts.

3. **Backend API (`tests/test_backend_api.py`)**
   - Uses `FastAPI TestClient` to directly exercise routes, bypassing the network stack for fast unit testing.
   - Verifies 401 unauthenticated drops, 422 validation drops, and 200 successes.

4. **Frontend UI (`frontend/tests/dashboard.test.jsx`)**
   - Uses `Vitest` and `React Testing Library (JSDOM)` to mount the dashboard offline.
   - Asserts that the UI does not crash or render blank screens when the API returns empty arrays or throws network timeouts.

5. **End-to-End Orchestration (`tests/e2e_poll.py`)**
   - Runs against the full `docker-compose.test.yml` stack.
   - Uses synthetic API injection (`POST /api/sync/events`) to simulate the Edge `SyncClient` payload.
   - Polls the backend `GET` routes until the data propagates, ensuring latency is recorded and no silent drops occur across the container boundaries.
