# FACE WATCHLIST END-TO-END VALIDATION COMPLETED

## Architecture

The authoritative path is `watchlist enrollment → protected backend sync →
edge Haar face detection in a verification zone → LBPH recognition → signed
EvidencePackage → backend Event/Alert persistence → protected REST and existing
WebSocket event fan-out → Dashboard camera card and Watchlist page`.  Camera ID
and stream/session ID remain part of the event scope; no cross-camera face
identity or ReID is inferred.

## Authoritative Recognition Engine

LBPH (`cv2.face.LBPHFaceRecognizer`) is the default and the only engine used by
the SIH demo acceptance path.  SFace/embedding code remains an explicit,
opt-in experimental path and is not silently substituted when unavailable.

## Enrollment and Image Validation

Admin-only enrollment and additional-image endpoints now reject invalid
base64, payloads over 2 MiB, non-images, tiny/near-uniform images, and images
without exactly one detectable face.  Reference images are never logged.
Multiple validated images per person are retained and included in a fresh
training run.  Raw bytes remain protected behind RBAC and are sent only to the
edge sync endpoint because the edge must train locally; production deployment
should move these bytes to encrypted object storage.

## Watchlist Synchronization

`GET /watchlist/sync` is edge-authenticated.  Startup and the periodic resync
build a fresh recognizer, so removed/inactive subjects do not remain in memory.
An empty or failed sync leaves the recognizer untrained and emits no fabricated
matches.

## Face Detection and Recognition

Detection is limited to person tracks in verification zones.  Haar is the
bundled CPU fallback; RetinaFace is used only when explicitly installed.  Each
evaluated event carries `face_match_status` (`KNOWN`, `UNKNOWN`,
`INSUFFICIENT_QUALITY`, or `NOT_EVALUATED`), `watchlist_person_id`,
`watchlist_label`, `recognition_score`, `recognition_threshold`,
`recognition_engine`, `face_quality_status`, `face_bbox_json`, and the legacy
compatible face fields.  Unknown or low-quality faces never become a high
severity watchlist alert.

## Threshold and Known/Unknown Behavior

The disclosed LBPH distance threshold is `FACE_RECOGNITION_THRESHOLD`, default
`60.0` (lower distance is stronger).  A score at or below the threshold is a
`KNOWN` match; a score above it is `UNKNOWN`.  Invalid/too-small crops are
`INSUFFICIENT_QUALITY`.  No probability or accuracy claim is attached to LBPH.

## Event, Alert, Persistence, and API Flow

Face metadata is carried by the signed edge package, persisted on `events`,
and exposed by `EventResponse`.  Migration `8c2f4a1b9d77` is applied to the
active SQLite database.  The protected bounded endpoint `/events/face` supports
camera, person, status, and time filters.  Existing event verification,
RBAC, WebSocket fan-out, and watchlist threat escalation remain in force.
Unknown faces retain the normal low/detected path and do not trigger a critical
alert.  Existing per-track event verification prevents frame-by-frame floods.

## UI

Dashboard camera cards now show the latest scoped face result (`MATCH`,
`UNKNOWN`, `INSUFFICIENT QUALITY`, or `No face evaluated`) and score without
inventing names or counts.  The unified event feed and Watchlist page remain
session/camera scoped.

## Security

Writes require admin RBAC; reads require an authenticated role; edge sync
requires edge authentication.  Image size/type/face-count validation is
server-side, base64 is not logged, query limits are bounded, and camera command
scoping is applied to historical face searches.  No cross-camera person key is
created.

## Executed Validation Data

- Real LBPH recognizer suite: **41 passed** (training, exact-match behavior,
  threshold acceptance/rejection, multiple images, color crops, decode failure,
  cascade loading, and edge wiring).
- Event/evidence regression: affected `test_backend_kid_propagation` passed;
  watchlist webhook regression passed.
- Frontend: **13 tests passed**; production Vite build passed.
- Live backend: `/health` returned 200; `/events/face` is present in OpenAPI
  and returns 401 without authentication as expected.
- Alembic migration `7f1b9a2c4d11 → 8c2f4a1b9d77` applied successfully.

## Performance

No face-specific FPS, latency, precision, recall, or accuracy number is
claimed.  The repository contains no consented real-person enrollment set and
no labeled face video suitable for an honest benchmark.  The controlled tests
validate functionality, not demographic or operational accuracy.

## Limitations

LBPH is sensitive to pose, lighting, and watchlist size; there is no liveness
detection; Haar may miss non-frontal faces; and reference images are currently
stored as protected base64 rows for the local demo.  A SIH operator must treat
`KNOWN` as an investigative lead requiring human review, not an automated
identity decision.  Full live known/unknown acceptance with a real enrolled
person remains **BLOCKED BY TEST DATA**, not presented as verified.
