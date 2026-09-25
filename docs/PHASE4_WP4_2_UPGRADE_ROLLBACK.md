# Phase 4 WP-4.2: Upgrade and Rollback

## Edge Upgrades
Upgrading an Edge node consists of pulling a new image and restarting the container.

### Upgrade Procedure
1. Pull the new edge image: `docker pull netraksh/edge:new_version`
2. Restart the service: `docker-compose -f docker-compose.edge.yml up -d`
3. The new container mounts the existing `edge_data` volume containing `local_queue.db`.
4. The `SyncClient` automatically begins processing the persistent offline queue.

### Edge Data Preservation
The Edge upgrade procedure **must never** delete the `edge_data` volume. If the volume is lost, any un-synchronized evidence in the local SQLite queue is permanently destroyed. The `edge/Dockerfile` does not mutate `/app/edge/data` during build.

### Edge Rollback
If the new Edge image fails to initialize properly, it can be seamlessly rolled back.
1. Re-tag or specify the previous image: `docker-compose -f docker-compose.edge.yml up -d`
2. The older version will safely resume parsing `local_queue.db`. (Note: Upgrades that fundamentally alter the SQLite schema of the offline queue are destructive and require careful migration strategies. No such schema changes exist currently).

## Central Upgrades
Central upgrades follow standard blue-green or rolling deployment strategies depending on the orchestrator.
- Schema migrations must be explicitly verified for backwards compatibility (e.g., using Alembic) to ensure edge nodes running older API schemas can still ingest events safely.
