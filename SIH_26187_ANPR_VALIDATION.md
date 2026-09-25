# Current Architecture

The authoritative path is now the enhanced edge path: vehicle track → LPD-YuNet
plate localization → quality gate → deterministic CLAHE/denoise/threshold
preprocessing → EasyOCR → confidence policy → Indian plate normalization and
validation → per-camera-track temporal fusion → event/evidence package → signed
edge sync → backend Event row → protected REST/WebSocket → dashboard.

# Root Problems Found

The runtime default was `ANPR_PIPELINE=legacy`, so a heuristic lower vehicle crop
could silently be used instead of the valid `lpd_yunet.onnx` artifact. The
enhanced fields already existed in the shared schema but were dropped by the
edge evidence packager and backend ORM/API. `PlateWatchlist.match()` was also a
permanent `None` stub.

# Authoritative Pipeline

`ANPR_PIPELINE=enhanced` is now the default. Legacy heuristic behavior remains
available only as an explicit compatibility setting. YuNet localization returns
bounded plate crops; invalid/degenerate/no-plate output is rejected without
crashing the worker. OCR is sampled per vehicle track (`ANPR_FRAME_INTERVAL`,
default 5) and requires `ANPR_OCR_MIN_CONFIDENCE` (default 0.55).

# Plate Localization

The repository-owned `lpd_yunet.onnx` is the valid 4,146,213-byte artifact and
passes its artifact/hash and runtime initialization tests. The similarly named
132-byte artifact is not selected. Localization uses vehicle-relative inference,
NMS, bounds checks, and a quality filter; the original crop remains available to
the evidence snapshot path.

# OCR

EasyOCR 1.7.2 executes through the enhanced wrapper and records raw text and
OCR confidence. Reads below the configured threshold become `LOW_CONFIDENCE` and
do not become ANPR events or watchlist alerts.

# Indian Plate Normalization

Normalization uppercases, removes harmless spaces/hyphens/dots and rejects
non-alphanumeric garbage. Validation is intentionally permissive for Indian
state, BH, temporary, and special formats: `VALID`, `PLAUSIBLE`,
`LOW_CONFIDENCE`, or `INVALID`.

# Temporal Consensus

Observations are keyed by camera-local vehicle track ID. The fusion buffer keeps
bounded history, records observation count and average/best confidence, and only
emits a confirmed plate after repeated compatible observations.

# Persistence

Raw text, normalized text, OCR/localization confidence, observation count,
processing method, fusion state, validation status, watchlist flag, vehicle
track ID, camera ID, stream/session ID, vehicle class, and event timestamp now
survive the EvidencePackage and backend Event contracts. Migration
`7f1b9a2c4d11_anpr_metadata.py` adds indexed `normalized_plate_text` storage.

# Search

Protected `GET /events/anpr` supports exact normalized plate, partial plate,
camera, start/end timestamps, bounded limit, and offset. It returns the normal
event response, including camera, timestamp, vehicle type, track, confidence,
event ID, and evidence/storage state.

# Watchlist

The fake always-`None` implementation is gone. An explicit, empty-by-default
edge configuration (`ANPR_WATCHLIST_PLATES`) provides normalized exact matches;
only confirmed, valid/plausible reads can set `watchlist_match` and critical
severity. No low-confidence read can alert. A persisted operator-managed plate
watchlist table is not yet implemented, so this remains a functional partial.

# Dashboard

Each active camera now shows a compact real ANPR value or `No plate read`, with
confidence. A scoped `RECENT NUMBER PLATE READS` table supports ALL/CAMERA 1/
CAMERA 2 filtering and uses the existing event/session filtering. No frontend
plate values are fabricated.

# Executed Validation Dataset

The repository-owned `demo/videos/vtest.avi` was processed through the actual
EdgePipeline for 40 frames. The run produced 9 signed evidence records and no
accepted plate reads; the early bounded clip segment did not contain a readable
plate. This is real-input functional validation, not a claimed CCTV accuracy
dataset. A synthetic/unit fixture validates normalization, confidence rejection,
temporal consensus, and enhanced metadata serialization.

# Metrics

No accuracy percentage is claimed. The real-input run measured 40 frames, 9
events, 1.62 FPS, mean total frame time 681.808 ms, p95 1,345.740 ms, and mean
event time 128.971 ms. ANPR exact matches: 0 on the executed real clip segment;
this is not a false-read rate because there was no labeled readable plate.

# Performance

Per-track OCR cadence defaults to every fifth call after the first observation.
The real run's total frame timing includes YOLO, tracking, health, behavior,
evidence, and OCR-capable event processing; it is a demo measurement, not a
production benchmark.

# Tests

- ANPR enhanced unit suite: **15 passed**.
- YuNet artifact/runtime suite: **7 passed** after installing the declared
  `onnxruntime==1.20.1` dependency.
- Frontend suite: **13 passed**.
- Frontend production build: **passed**.
- Python syntax/schema checks: **passed**.
- The existing 200-frame integration test was blocked by the host's locked
  shared pytest temp directory; the isolated 40-frame real-input script ran
  successfully and produced the metrics above.

# Limitations

The supplied vtest clip segment contains no labeled readable plate, so ANPR is
`VERIFIED PARTIAL`, not accuracy-validated. EasyOCR remains CPU-heavy. The
watchlist is explicit edge configuration rather than a persisted plate-watchlist
table. Distributed deployments must upload evidence bytes rather than relying on
the current shared-filesystem path. A controlled synthetic plate fixture or
operator-provided non-sensitive plate video is still required for a genuine
edge → backend → DB → API → UI accepted-plate walkthrough.
