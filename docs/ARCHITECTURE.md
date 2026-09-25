# NETRAKSH — Architecture Document
# AI-Based Intelligent Video Analytics Platform for Border Surveillance
# SIH 2026, Problem Statement #187, Team SecureX
# This document is generated and maintained by the engineering agent.
# It is the living record of what was actually built vs. the original design.

## Phase 0 Environment Spike Results

| Check | Status | Detail |
|-------|--------|--------|
| Python 3.14.7 | ✅ CONFIRMED | `pip` 26.2.1 |
| pip install (full dependency list) | ✅ CONFIRMED | All packages installed successfully. See section below. |
| `import ultralytics` | ✅ CONFIRMED | ultralytics 8.4.137, YOLO import succeeds |
| `import cv2` | ✅ CONFIRMED | OpenCV 5.0.0.93 |
| `import easyocr` | ✅ CONFIRMED | easyocr 1.7.2 |
| `import retina_face` | ⚠️ PARTIAL | `retina-face` package installed but import path is `retina_face`. See note. |
| `import sklearn` | ✅ CONFIRMED | scikit-learn 1.9.0 |
| `import cryptography` | ✅ CONFIRMED | cryptography 42.x |
| `import fastapi`, `uvicorn` | ✅ CONFIRMED | fastapi 0.141.1, uvicorn 0.52.4 |
| `import sqlalchemy`, `alembic` | ✅ CONFIRMED | SQLAlchemy 2.0.52, Alembic 1.19.1 |
| `import psycopg2` | ✅ CONFIRMED | psycopg2-binary 2.9.12 |
| Node.js | ✅ CONFIRMED | Node.js 24.19.0 (LTS) |
| WSL2 | ❌ NOT INSTALLED | Not available on this machine |
| Docker Desktop | ❌ NOT AVAILABLE | Requires WSL2 — not installed |
| Hyperledger Fabric `test-network` | ❌ NOT POSSIBLE | Docker required |
| PostgreSQL | ⏳ INSTALLING | EDB installer running |

### Confirmed Package Versions
```
ultralytics       8.4.137
opencv-python     5.0.0.93
easyocr           1.7.2
scikit-learn      1.9.0
cryptography      42.x
fastapi           0.141.1
uvicorn           0.52.4
sqlalchemy        2.0.52
alembic           1.19.1
psycopg2-binary   2.9.12
httpx             0.28.1
torch             2.13.0
torchvision       0.28.0
pytest            9.1.1
pydantic          2.13.5
```

---

## DECISION POINT RESOLUTIONS

### DP-1: Docker / Hyperledger Fabric
**Outcome: MOCK ADAPTER committed for this build.**

Rationale:
- WSL2 is not installed on this machine.
- Docker Desktop requires WSL2 on Windows.
- Without Docker, Hyperledger Fabric `test-network` cannot run.
- Timebox: the Phase 0 half-day spike identified this immediately.

**What this means:**
- `blockchain/client/mock_adapter.py` is the active blockchain adapter.
- The `FabricCLIAdapter` class exists in `backend/services/blockchain.py` and implements the identical interface — switching to real Fabric requires setting `BLOCKCHAIN_MODE=fabric` in `.env` and ensuring `peer` CLI is on PATH.
- Every place the mock is used is clearly labelled: in code comments, in `docs/LIMITATIONS.md`, and in the dashboard UI (`BLOCKCHAIN_MOCK_LABEL` env var).

**What the mock does not claim:**
- It does NOT simulate Byzantine fault tolerance.
- It does NOT simulate cross-org consensus.
- It DOES implement the exact same interface contract (AlertIssued / AlertAcknowledged) that real Fabric chaincode would expose.

### DP-2: Python version
**Outcome: Python 3.14 confirmed working — no downgrade needed.**

All packages installed and imported successfully. PyTorch 2.13.0 and Ultralytics 8.4.137 both support Python 3.14.

### DP-3: RetinaFace
**Outcome: Installed. Used as secondary detector, Haar cascade as primary fallback.**

`retina-face==0.0.17` installed. The face detection module uses RetinaFace when available, with OpenCV Haar cascade as fallback. Face recognition (ArcFace) is explicitly NOT in MVP scope.

---

## System Architecture Summary

### 3-Gate Reliability Pipeline (LOCKED)

```
Camera Frame
    │
    ▼
Gate 1: Camera Health Monitor
    ├── OK     ──────────────────────────────────────────────┐
    ├── DEGRADED ─────────────────────────────────────────── │ continue
    └── FAILED  ─────────────────→ ABSTAIN (stop here)       │
                                                             │
    ▼                                                        │
Gate 2: Scene Condition Classifier                           │
    ├── CLEAR_DAY      → threshold_clear_day (0.45*)         │
    ├── LOW_LIGHT_NIGHT → threshold_night (0.30*)            │
    ├── FOG_RAIN       → threshold_fog (0.35*)               │
    └── GLARE          → threshold_glare (0.40*)            │
         * = prototype values, not calibrated                │
                                                             │
    ▼                                                        │
Gate 3: Calibrated Confidence                               │◄─────
    ├── confidence < threshold → UNCERTAIN                   │
    └── confidence ≥ threshold:                              │
        ├── health == DEGRADED → DETECTED (flagged)         │
        └── health == OK       → DETECTED                   │
```

### On-Chain vs Off-Chain Split (LOCKED)

**On-chain ONLY (AlertIssued transaction):**
- alert_id, evidence_package_hash, severity, zone_id
- issuing_command_id, timestamp

**On-chain ONLY (AlertAcknowledged transaction):**
- alert_id, receiving_command_id, ack_timestamp, status, signature

**Off-chain (PostgreSQL):**
- All video, all events, all health history
- All detection details, tracks, dashboard state
- Full evidence package metadata

**Never on-chain:**
- Video clips
- Continuous health data
- Raw detection confidences
- Camera streams

### Edge-Server Architecture

```
Edge Device (per camera)
├── Layer 1: Camera Adapter (OpenCV, file/RTSP/webcam)
├── Layer 2: Health Monitor (Gate 1) + Condition Classifier (Gate 2)
├── Layer 3: YOLO+ByteTrack Detector (Gate 3, calibrated threshold)
├── Layer 4: Task Modules (fence, loitering, ANPR, face detection)
├── Layer 4.5: Event Verifier — CANDIDATE → VERIFIED/ALERTED state machine
│             (edge/temporal/event_verifier.py — see §Event Verification below)
├── Layer 5: Reliability Decision (DETECTED/UNCERTAIN/ABSTAIN)
├── Layer 6: Evidence Packager (SHA-256, Ed25519, SQLite hash-chain)
└── Layer 7: Sync Client (store-and-forward, SIMULATE_OFFLINE mode)

Backend Server (FastAPI + PostgreSQL)
├── REST API (events, alerts, cameras, auth, system)
├── WebSocket (live dashboard push)
├── Verification Service (hash+sig+chain re-verification on demand)
├── Escalation Engine (severity+jurisdiction → AlertIssued)
├── Blockchain Client (mock adapter / Fabric CLI)
└── RBAC (ADMIN / OPERATOR / AUDITOR)

Frontend (React + Vite)
└── Dashboard (live feed, camera map, evidence viewer, alert board)
```

---

## Event Verification (added — architecture v4 §9, Priority 3)

**What changed:** task modules (fence, loitering, abandoned object, ANPR, face) no longer trigger
evidence packaging directly. A new `edge/temporal/event_verifier.py` sits between the task modules
and `EvidencePackager` in `edge/main.py`, implementing the state machine:

```
OBSERVED → CANDIDATE → [held while Reliability=UNCERTAIN] → VERIFIED → ALERTED → ACKNOWLEDGED → CLOSED
```

- A task module firing is a **CANDIDATE** only. No evidence is generated at this point.
- A candidate needs `N` confirmations (the *same* condition observed again on a later frame, with
  Gate 3's Reliability decision = DETECTED) before promotion to **VERIFIED/ALERTED**, where evidence
  packaging finally happens. `N` is 3 for `VIRTUAL_FENCE_CROSSING` (the event type most exposed to
  one-frame tracking jitter) and 1 for loitering/abandoned/ANPR/face, whose own task-module logic
  already requires sustained dwell/stationary time before ever firing a candidate.
- A frame where Reliability is UNCERTAIN **holds** the candidate (no progress lost, no promotion
  either) rather than discarding or force-confirming it.
- A candidate not reconfirmed within `max_gap_frames` (default 5) expires with **no evidence
  generated at all** — this is the concrete mechanism behind the "a single noisy frame cannot become
  an alert" claim in the pitch.
- A 30-second cooldown after ALERTED prevents a still-true condition from spamming duplicate alerts
  every frame.

**Why:** previously, `VirtualFenceModule.check()` firing once on a crossing transition went straight
to `EvidencePackager.package()` the same frame — a single-frame tracking-jitter crossing (track
briefly wobbles across a zone boundary and back) would have generated a real, signed, chained,
alerted piece of evidence. It now requires the track to remain on the new side of the boundary for
3 consecutive re-checks first.

**What did NOT change:** `VirtualFenceModule`, `BehaviorModule`, `ANPRModule`, `FaceDetectionModule`,
`CameraHealthMonitor`, `SceneConditionClassifier`, `DetectionTracker`, and `make_reliability_decision`
are all untouched. Loitering/abandoned/ANPR/face behavior is functionally unchanged (they auto-verify
on their first DETECTED observation, same as their previous immediate-alert behavior) — only fence
crossing gained the multi-frame confirmation requirement.

**Tests:** `tests/unit/test_event_verifier.py` (11 new tests: single- vs multi-frame confirmation,
UNCERTAIN-holds-without-resetting, stale-candidate expiry, cooldown, per-track key isolation). Full
suite: 37 pre-existing tests + 11 new = 48 passed, 0 failed, 0 broken.

---

## Performance Instrumentation (added — architecture v4 §15, MUST HAVE)

**What changed:** a new `edge/instrumentation/metrics.py` (`PipelineMetrics`) records real,
locally-clocked latency at every pipeline stage instead of asserting "real-time" without evidence:

- **Per-frame** (every frame, event or not): `health_condition_ms`, `detection_tracking_ms`,
  `event_processing_ms`, `total_frame_ms`, plus FPS measured over a rolling window of actual frame
  timestamps (not the declared/configured rate).
- **Per-event** (only frames where the Event Verifier — see above — actually promotes a candidate to
  VERIFIED/ALERTED): `snapshot_ms`, `hash_sign_ms`, `chain_store_ms`, `enqueue_ms`, `total_event_ms`.
  `EvidencePackager.package()` now records these three timings into a new `self.last_timing` dict
  attribute on every call — its `(package, seq_num)` return contract is unchanged.
- **Resource usage** (CPU%/RSS): sampled via `psutil` if installed (now a soft/optional line in
  `requirements.txt`); if not installed, these fields report `null`, never a fabricated number.

Every stage is `time.perf_counter()`-timed (monotonic, sub-millisecond) and kept in a bounded rolling
window (mean/P95/max/min via nearest-rank percentile) so memory stays flat during a long demo.
`EdgePipeline` logs a one-line summary and writes `edge/data/metrics_<camera_id>.json` every
`metrics_report_interval_seconds` (default 10s). `scripts/print_performance_report.py` prints a
formatted report from that JSON, and `docs/PERFORMANCE_REPORT.md` is the template to fill in with a
real run before the numbers go in the PPT — see that file for the exact procedure, including the
before/after test needed to back any false-positive-reduction percentage with real counts instead of
an estimate.

**What did NOT change:** no existing pipeline stage's behavior or output changed — this is
read-only instrumentation wrapped around calls that already happen. `EvidencePackager.package()`'s
return signature is untouched (timing is exposed via an extra instance attribute, not a return-value
change), so the one existing call site (`edge/main.py::_emit_event`) and any future caller are
unaffected if they don't read `last_timing`.

**Tests:** `tests/unit/test_metrics.py` (16 new tests: percentile math, rolling-window stats, FPS via
an injectable fake clock, frame/event recording, honest resource-sampling fallback, JSON dump). Full
suite: 48 pre-existing tests + 16 new = 64 passed, 0 failed, 0 broken.

---

## Evidence-at-Rest Encryption (added — architecture v4 §10, MUST HAVE)

**What changed:** `edge/evidence/packager.py` gained a new `EvidenceEncryptor` class (AES-256-GCM,
authenticated encryption — tamper on the ciphertext is detected on decrypt, no separate MAC needed).
`EvidencePackager._save_snapshot()` now JPEG-encodes the frame in memory, encrypts those bytes before
anything touches disk, and writes a `.jpg.enc` file instead of a plain `.jpg`. The AES-256 key is
generated once per edge device and stored alongside the existing Ed25519 identity key
(`certs/edge/<camera_id>.aes`), following the same generate-once-then-load pattern as
`EdgeKeyManager`.

**What did NOT change:** `EvidencePackager.package()`'s `(package, seq_num)` return contract is
identical — encryption is fully internal. The one existing call site (`edge/main.py::_emit_event`)
required no changes at all. Nothing on the backend or dashboard was reading `evidence_clip_ref` and
serving it as an image before this change (confirmed by inspection — `backend/main.py`'s
`FileResponse` usage is for the frontend SPA build, unrelated to evidence clips), so there was no
plaintext-serving path to break.

**What is still open:** a backend/dashboard endpoint that reads an encrypted clip and decrypts it for
an authorized, RBAC-gated viewer does not exist yet — see `docs/LIMITATIONS.md` §3.

**Tests:** `tests/unit/test_evidence.py` gained `TestEvidenceEncryptor` (7 tests: key generation,
deterministic reload, malformed-key rejection, encrypt/decrypt round-trip, nonce uniqueness, tamper
detection, wrong-key rejection) and `TestEvidencePackagerAtRestEncryption` (2 tests: the on-disk file
is verifiably not a readable JPEG and decrypts back to a valid one; the return contract is
unchanged). Full suite: 64 pre-existing tests + 9 new = 73 passed, 0 failed, 0 broken.

---

## Hybrid Reliability Engine (added — architecture v4 §8, MUST HAVE)

**What changed:** `edge/reliability/decision.py`'s Gate 3 (raw confidence vs. a single per-condition
threshold) is replaced by a weighted-sum Reliability score:

```
Gate 1 (unchanged, hard override): health == FAILED -> ABSTAIN, stop.
Else:  R = wD*D + wT*T + wS*S + wH*H
       R < RELIABILITY_R_THRESHOLD (0.75)  -> UNCERTAIN
       R >= RELIABILITY_R_THRESHOLD        -> DETECTED (flagged if health == DEGRADED)
```

- **D** = raw detector confidence (unchanged input).
- **T** = temporal consistency, computed by a new `edge/temporal/track_features.py`
  (`TrackFeatureTracker`) — Mode A per `docs/ADR-TEMPORAL.md`: a hand-weighted average of track age,
  path smoothness, and speed consistency, needing zero labeled training data. Defaults to a neutral
  `1.0` when no track context is available (e.g. an abandoned-object event whose track has already
  disappeared).
- **S** = scene quality, a new continuous score derived from `SceneConditionReport`'s existing raw
  brightness/contrast/glare signals (previously only their *categorical* bucket was used).
- **H** = camera health quality (`OK`→1.0, `DEGRADED`→0.5; `FAILED` never reaches this — Gate 1
  handles it exclusively).
- Weights (`RELIABILITY_WEIGHT_D=0.40`, `_T=0.20`, `_S=0.20`, `_H=0.20`) and
  `RELIABILITY_R_THRESHOLD=0.75` are hand-picked heuristic defaults, not calibrated — all five are
  environment-overridable. `calibration_threshold` (the per-condition value from
  `edge/detection/calibration.py`) is still passed in and still gates what confidence YOLO itself
  reports as a candidate detection, and is still echoed into `applied_threshold` for context — it no
  longer drives the DETECTED/UNCERTAIN split itself.
  A real attempt was made to fit these weights from labeled data
  (`scripts/collect_calibration_data.py` + `scripts/fit_reliability_weights.py`, against the same
  real video/zone as `docs/PERFORMANCE_REPORT.md`, plus two synthetic night/fog variants of it):
  manual review of every real candidate in all three found zero false positives to learn from, so the
  fit was correctly refused rather than faked. That same labeled data did surface a real, actionable
  bug though — under fog, a double penalty (contrast loss counted once via `S` and again via `H`,
  because the same blur that lowers scene quality also genuinely trips the Camera Health Monitor's
  blur detector) meant 0/52 genuine crossings ever reached DETECTED. `_health_quality_score` now
  exempts exactly that overlap (`EXCESSIVE_BLUR` + `FOG_RAIN`/`LOW_LIGHT_NIGHT`), which real
  re-measurement raised to 37/52 (71%). A second fix followed the same real diagnosis pattern:
  `_scene_quality_score`'s contrast component was judging FOG_RAIN frames against a clear-day
  contrast ideal (60.0) they can never meet by definition, when the real, already-existing
  `FOG_CONTRAST_THRESHOLD` (30.0) — literally the rule that classifies a scene as foggy in the first
  place — is the honest reference to use instead. That raised fog further, to 45/52 (87%). A third fix
  did the same for night's own bottleneck: `brightness_score` judged `LOW_LIGHT_NIGHT` frames against
  the same clear-day ideal (128.0), when the real, already-existing `BRIGHTNESS_NIGHT_THRESHOLD` (60.0)
  — literally the rule that classifies a scene as night in the first place — is the honest reference
  to use instead. That raised night from 21/51 (41%) to 31/51 (61%). A fourth fix addressed night's
  remaining contrast-side gap too, but is disclosed as a different kind of fix from the three above:
  `LOW_LIGHT_NIGHT`'s classification rule has no contrast component to reuse the way `FOG_RAIN` and
  night's own brightness fix could, so `_SCENE_CONTRAST_GOOD_NIGHT` (half of
  `BRIGHTNESS_NIGHT_THRESHOLD`) is a genuinely new, hand-picked heuristic — justified by a real
  physical property (a non-negative pixel distribution capped near a low mean can't have much spread
  without clipping), not a reused classification-boundary constant. That raised night further, to
  39/51 (76%). **A fifth fix, found while investigating why 3/52 DAYTIME crossings still missed
  threshold despite S≈0.92 and H=1.0 (no scene/health issue at all), turned out to be a real,
  previously-shipped production bug — not a calibration-side issue like the four above.**
  `edge/temporal/track_features.py`'s `TrackFeatureTracker` only ever had its per-track `_first_seen`
  bookkeeping registered inside `compute()` — and both `edge/main.py` and
  `scripts/collect_calibration_data.py` only ever call `compute()` from an EVENT-triggered branch (a
  fence-crossing handler, which fires once per track at the crossing transition). That means
  `_first_seen[track_id]` got set at the moment of a track's first qualifying event, not its real
  first-observed frame — so `age_seconds` was **always 0.0** on that first (and often only) call,
  regardless of how long the track had genuinely already been tracked (measured directly: the 3
  daytime candidates each had 34-50 real trajectory points — 1.4-2 real seconds of prior tracking —
  yet `T_age_score` was exactly `0.0` for all three). The fix: a new `TrackFeatureTracker.observe()`
  method, called unconditionally for every active track every frame in both `edge/main.py` and the
  collection script — independent of whether any rule event fires that frame — so age is registered
  as soon as a track is truly first seen (4 new tests,
  `tests/unit/test_track_features.py::TestObserveFixesEventTriggeredAgeZeroing`; full suite
  227/227). Re-measured result, across ALL THREE conditions at once (this bug was condition-
  independent): daytime rose from 49/52 (94%) to **52/52 (100%)**; night from 39/51 (76%) to
  **47/51 (92%)**; fog from 45/52 (87%) to **49/52 (94%)** — by a wide margin the largest single fix
  this session, since it corrects a genuine defect in the real, deployed edge pipeline itself, not
  just a calibration-script measurement. **A sixth fix generalized fix 1's H-exemption for a fourth
  real `SceneCondition`, GLARE.** A synthetic glare transform (scale pixels ×1.8+20, clip at 255)
  reliably classified `GLARE` via the real `glare_fraction` path, and found the SAME real
  double-penalty pattern fix 1 fixed for fog/night: glare genuinely blows out highlights (penalized
  by `S`), and the same overexposure genuinely trips the Camera Health Monitor's own exposure-clipping
  check into `ABNORMAL_EXPOSURE` (which used to *also* halve `H`) — initially 0/55 (0%) DETECTED,
  identical in shape to fix 1's original finding. Rather than special-case it, fix 1's single
  hardcoded exemption became a real `_WEATHER_EXPLAINED_DEGRADED_REASONS` mapping —
  `{EXCESSIVE_BLUR: {FOG_RAIN, LOW_LIGHT_NIGHT}, ABNORMAL_EXPOSURE: {GLARE}}` — so a third such
  pairing is a one-line addition, not new code. Re-measured: glare rose from 0/55 (0%) to 33/55 (60%).
  Unlike fog/night, glare's remaining 40% was checked and found to be a genuinely different
  situation, not a further reference-point bug: GLARE's classification (`glare_fraction > 0.15`) has
  no structural ceiling the way fog/night's rules do (which guarantee every classified instance fails
  the old reference) — this specific transform's severity (~0.43, well past the 0.30 point where
  `glare_score` fully floors) is a transform-intensity limitation, not a formula defect.
  **A seventh fix reached into `edge/condition/scene_condition.py` itself** — the first fix this
  session to touch the classifier rather than only the Reliability Engine. A real fog+glare compound
  scene (a light source cutting through daytime fog) is classified `GLARE` (its check runs first), so
  fix 6's exemption cannot see it; a same-condition contrast check (`contrast_std < FOG_CONTRAST_THRESHOLD`)
  was tried first but, at real scale, found NOT to catch this case — a small bright glare region
  inflates the frame's whole-frame `contrast_std` (≈41) well past the threshold even though the hazy
  non-glare majority of the frame is genuinely foggy. `SceneConditionClassifier` now also computes
  `contrast_std_excluding_glare` (spread among non-blown-out pixels only), and the exemption uses that
  instead — `_decide()`'s own classification is deliberately untouched, so this affects only the
  exemption's internal check, not what condition a frame is classified as. Re-measured: `fog_glare`
  rose from 0/52 (0%) to 37/52 (71%), matching the hypothetical prediction exactly. See
  `docs/LIMITATIONS.md`'s Hybrid Reliability Engine entry and `docs/PERFORMANCE_REPORT.md`'s
  night/fog/glare section for the full, honest before/after of all seven fixes. `D/T/S/H`'s hand-picked
  *weight values* themselves remain unchanged — these fixed how `H`, `S`, and `T` are computed, not
  the weights applied to them — pending real labeled data with actual false positives to fit against.

**Intentional behavior change — read this before assuming a regression:** under the old cascade, a
lower per-condition confidence threshold made night/fog detections *easier* to accept (a compensating
leniency). Under the hybrid formula, degraded scene quality instead *reduces* R (via S), so a night
detection now needs the **same** evidentiary bar as a clear-day one, not an easier one. This is
deliberate, not a bug: the project's own thesis is that the system should trust itself **less** under
degraded conditions, not accept weaker evidence as if it were normal. One existing test
(`test_night_condition_uses_lower_threshold`) tested exactly the retired leniency and was rewritten —
see `TestHybridEngineIntentionalNightBehaviorChange` in `tests/unit/test_reliability.py` for the
replacement, which locks in the new, intended behavior with a comment explaining why.

**What did NOT change:** Gate 1's FAILED-camera hard override is byte-for-byte the same logic as
before — a weighted sum cannot provide this guarantee on its own, which is exactly why it stays a
categorical check ahead of the formula. `make_reliability_decision()`'s existing four positional
arguments are unchanged; `temporal_score` is a new optional keyword defaulting to a neutral `1.0`, so
any caller not yet upgraded to compute it sees the same numeric behavior as passing `1.0` explicitly
(verified by `test_default_temporal_score_is_neutral_one`).

**Tests:** `tests/unit/test_reliability.py` — 19 pre-existing tests became 26 (one rewritten with a
documented rationale, six new: banding boundaries, the intentional night-behavior tests, T's real
effect on a borderline case, and the weight configuration itself). New
`tests/unit/test_track_features.py` (11 tests: track age, bounded output, straight-line vs. zigzag
smoothness — including a caught-and-fixed bug where variance-of-turning-angle wrongly scored a
*regular* zigzag as smooth, corrected to mean-turning-magnitude — stationary-track handling,
insufficient-data defaults, age saturation). Full suite: 73 pre-existing + 7 net new in
`test_reliability.py` + 11 new in `test_track_features.py` = 91 passed, 0 failed, 0 broken.

---

## Track Continuity Guard (added — architecture v4 §4, MUST HAVE, closes v3/v4 Risk #2)

**What changed:** two independent, additive layers mitigate ByteTrack ID fragmentation under brief
occlusion — no learned Re-ID, classical CV only, matching the same "hand-crafted over learned, for
this problem size" philosophy as `docs/ADR-TEMPORAL.md`:

1. **`edge/config/bytetrack_border.yaml`** — a copy of ultralytics' bundled tracker config with
   `track_buffer` raised from the default 30 frames (~1s) to 120 (~4s), so ByteTrack itself waits
   longer before giving up on a lost track. `edge/detection/detector.py::DetectionTracker` now
   resolves this path by default (with a two-level fallback: an explicit path if the caller passes
   one, then this border-tuned config, then ultralytics' own bundled default if even that file is
   somehow missing — never a hard crash over a missing config file).
2. **`edge/tracking/continuity_guard.py` (`TrackContinuityGuard`)** — a second layer that recovers
   identity even *after* ByteTrack has given up and assigned a brand-new ID. Every active track's HSV
   color histogram + centroid is snapshotted each frame (`edge/main.py`); when a track disappears, its
   snapshot moves into a short-lived "lost pool" (5s TTL); when a genuinely new track ID appears, it's
   checked against that pool by histogram similarity (`cv2.compareHist`, correlation method) and
   spatial proximity. Above both thresholds, the new detection's `track_id` **and** `trajectory` are
   rewritten in place to the recognized identity, and the merge is logged
   (`[Pipeline] Track X re-associated with recently-lost track Y`) — never applied silently.

**Where this is applied in the pipeline:** `EdgePipeline._apply_continuity_guard()` runs immediately
after `detect_and_track()`, before trajectory storage, T-feature age tracking, or any task module sees
the track. Because re-association happens this early, `VirtualFenceModule`'s zone-membership state,
`BehaviorModule`'s dwell/stationary tracking, and `TrackFeatureTracker`'s age tracking all resume
automatically from where the original track left off — none of those modules needed to change.

**What did NOT change:** `VirtualFenceModule`, `BehaviorModule`, `ANPRModule`, `FaceDetectionModule`,
the Hybrid Reliability Engine, and the Event Verifier are all untouched — the guard operates entirely
upstream of them, on track identity only.

**Tests:** `tests/unit/test_continuity_guard.py` (15 tests: histogram+proximity matching, pool
removal on match, dissimilar/far/expired/no-pool non-matches, best-of-multiple-candidates selection,
TTL expiry, `compute_histogram`'s bounds-clipping and degenerate-crop handling) and
`tests/unit/test_detector_tracker_config.py` (5 tests: default/explicit/fallback config resolution,
the shipped `track_buffer` value itself). Full suite: 91 pre-existing + 20 new = 111 passed, 0 failed,
0 broken.

---

## Line Crossing Event Type (added — architecture v4 §5, HIGH VALUE, near-free)

**What changed:** a new `edge/rules/modules.py::LineCrossingModule` detects a tracked object's
centroid crossing a configured 2-point line segment, exactly as v4 described it: "a line is just a
degenerate polygon edge with directional crossing logic." It reuses `ZoneType.BOUNDARY` — already
defined in `shared/constants.py` but unused by any module until now — for zones with exactly 2
polygon points. Side is determined by the sign of a 2D cross product; direction is reported as a new
`LineCrossingDirection` (`A_TO_B` / `B_TO_A`, relative to the order of the two configured points — a
line has no inherent inside/outside, so this doesn't presume one the way `FenceDirection` does).
`EventType.LINE_CROSSING` is a new enum value. It shares the fence module's exposure to single-frame
tracking jitter, so it shares the same 3-confirmation depth in the Event Verifier (the confirmation
count was already reserved there — `edge/temporal/event_verifier.py`'s
`DEFAULT_REQUIRED_CONFIRMATIONS["LINE_CROSSING"]` — before this module existed to use it) and the
same "pending re-check" wiring in `edge/main.py` as fence crossing, checking
`LineCrossingModule.get_track_side()` instead of `VirtualFenceModule.get_track_zone()`.

**A real cross-module bug caught and fixed along the way:** `EvidencePackage.direction`
(`shared/schemas.py`) was typed `Optional[FenceDirection]`. Constructing an evidence package for a
line-crossing event would have thrown a Pydantic `ValidationError` at the first real line crossing —
`LineCrossingDirection.A_TO_B` isn't a valid `FenceDirection` member. Fixed by widening the field to
`Optional[str]`, which matches how `backend/models/orm.py` already stores this column (`String(32)`)
and doesn't require touching the locked field *name*, only its type. Covered by a new regression test,
`test_line_crossing_direction_is_accepted_alongside_fence_direction` in `tests/unit/test_evidence.py`.

**Severity:** `determine_severity()` assigns `LINE_CROSSING` a flat `MEDIUM` — deliberately not tiered
by direction the way fence crossing is (`OUTSIDE_TO_RESTRICTED` → `HIGH`), because a line has no
zone-specific "the dangerous direction" configuration the way a fence polygon's inside does. Neither
`A_TO_B` nor `B_TO_A` can be assumed more severe without that context.

**Real gap found, not new to this change:** `demo/scripts/zones_config.json` is currently `{"zones":
[]}` — empty. This means **every** zone-scoped task module (fence, line crossing, ANPR checkpoint,
face verification) is dormant in the current demo config, not just the new one. Real zone coordinates
matching the actual demo camera's framing need to be added before any of these can be shown live —
see `docs/LIMITATIONS.md`.

**What did NOT change:** `VirtualFenceModule`, `BehaviorModule`, `ANPRModule`, `FaceDetectionModule`,
the Hybrid Reliability Engine, the Event Verifier's core logic, and the Track Continuity Guard are all
untouched.

**Tests:** `tests/unit/test_line_crossing.py` (12 tests: zone-type/point-count filtering, no-fire on
first observation or same-side movement, crossing detection both directions, on-the-line ambiguity
handling, per-track isolation, multi-line independence) plus one new test each in
`tests/unit/test_evidence.py` (the direction-type regression above) and
`tests/unit/test_event_verifier.py` (confirms the reserved 3-confirmation depth is actually exercised
end-to-end now). Full suite: 111 pre-existing + 14 new = 125 passed, 0 failed, 0 broken.

---

## Adaptive Compute Gate (added — architecture v4 §6, HIGH VALUE)

**What changed:** a new `edge/detection/adaptive_gate.py::AdaptiveComputeGate` skips full YOLO
inference on frames that are genuinely idle — no motion, no active track, no candidate event pending
in the Event Verifier — running it only once every `IDLE_INFERENCE_INTERVAL_FRAMES` (default 5)
frames during that state, and every frame otherwise. It reuses `CameraHealthMonitor`'s existing
frame-difference variance signal (`CameraHealthReport.frame_variance`) against a new, higher threshold
(`MOTION_GATE_VARIANCE_THRESHOLD = 15.0`, deliberately above `FROZEN_FRAME_VARIANCE_THRESHOLD = 5.0` —
a frame that reaches this gate is guaranteed not frozen, since Gate 1 already handled that case) — no
new expensive per-frame computation is added anywhere.

**Why gating on "no active tracks" is what makes this safe:** ByteTrack needs continuous per-frame
detection to maintain a track's identity and trajectory — skipping inference on a frame with an active
track would look identical to that track disappearing, incorrectly triggering the stale-track cleanup
and Track Continuity Guard handoff built in earlier turns. The gate's `has_active_tracks` check makes
this impossible by construction: it only ever enters IDLE (and only ever skips) when
`self._trajectories` is already empty, so there is nothing to lose. The moment a real object enters
frame, the next full-rate inference tick (at most `idle_interval_frames` away) detects it, creates a
track, and `has_active_tracks` permanently forces full-rate inference again until that track
naturally ends.

**Where it's applied:** `EdgePipeline._process_frame()`, between the (always-run) Gate 1/Gate 2
health/condition checks and the detector call. Skipped frames record `detection_tracking_ms=0.0` in
the existing performance instrumentation — a real, visible number proving the compute saving, not a
claim.  Gate stats (state, frames run/skipped, skip ratio) are logged every metrics-report interval
and persisted into the same `edge/data/metrics_<camera_id>.json` via `PipelineMetrics.dump_json()`'s
new optional `extra` merge parameter (added specifically for this, without `PipelineMetrics` needing
to know anything about the gate that produced the extra fields).

**Deliberately NOT implemented — scope reduction, recorded honestly:** v4 §6 describes four tiers
(idle / object-present / candidate-forming / verified), the last two adding a higher-resolution crop
and full-resolution processing. This implementation has exactly two tiers (IDLE / ACTIVE) and never
changes resolution at any tier — there is no resolution reduction to "restore." This is the core,
highest-value half of the idea (the actual compute saving during idle periods); the resolution-tiering
half is real future work, not something to claim as done. See `docs/LIMITATIONS.md`.

**What did NOT change:** the detector, ByteTrack, the Track Continuity Guard, the Hybrid Reliability
Engine, and the Event Verifier are all untouched — the gate only decides whether `detect_and_track()`
gets called at all this frame; everything downstream is unaware it was skipped.

**Tests:** `tests/unit/test_adaptive_gate.py` (12 tests: idle/active classification on all three
inputs, exact interval scheduling — including a hand-traced 9-call sequence — countdown reset on the
idle→active transition, and stats tracking) plus 2 new tests in `tests/unit/test_metrics.py` for
`dump_json()`'s new `extra` parameter. Full suite: 125 pre-existing + 14 new = 139 passed, 0 failed,
0 broken.

---

## CLAHE Preprocessing + Night-Motion Fallback Wiring (added — architecture v4 §3, HIGH VALUE)

**What changed — two independent pieces closing out the last open item from architecture v4 §3:**

1. **CLAHE preprocessing** (`edge/condition/preprocessing.py::enhance_for_detection`): before
   `detect_and_track()` runs on a frame classified `LOW_LIGHT_NIGHT` or `FOG_RAIN`, a CLAHE-enhanced
   *copy* of the frame (LAB color space, CLAHE on the L channel, hand-picked `clipLimit=2.0`,
   `tileGridSize=(8,8)`) is built and passed to the detector instead of the original. Camera health,
   scene condition classification, evidence snapshots, and ANPR/face crops all continue to use the
   original, unmodified frame — enhancing before classification would make a genuinely dark/foggy
   scene measure as better than it is, corrupting the Hybrid Reliability Engine's `S` signal, which
   depends on that measurement being honest.
2. **Night-motion fallback wired in** (`edge/main.py`): `NightMotionFallback` — real code that existed
   since the original MVP but was never called from anywhere, confirmed dead by inspection before this
   change — now runs when a frame is `LOW_LIGHT_NIGHT`, YOLO found zero tracks, and we actually ran
   inference this frame (skipping this check on an Adaptive-Compute-Gate-skipped frame would be
   redundant with that gate's own, different motion signal already having said "no motion"). On
   detected motion, it emits a `MOVEMENT_UNCLASSIFIED` evidence record via the already-existing
   `make_uncertain()` helper — honestly labeled `UNCERTAIN`, never `DETECTED` — throttled by a new
   `NIGHT_MOTION_COOLDOWN_SECONDS` (30s) so continuous motion doesn't flood evidence storage with a
   snapshot every frame.

**A real design question worked through, not glossed over:** should this route through the Event
Verifier (architecture v4 §9) like every other event type? No — deliberately not. The Event Verifier
only counts frames where the accompanying Reliability decision is `DETECTED` toward confirmation,
and `make_uncertain()` always returns `UNCERTAIN` by construction. Routing this through
`submit_candidate()` would create a `CANDIDATE` that can mathematically never be promoted, silently
producing zero evidence — exactly the outcome this feature exists to avoid. It's emitted directly via
`_emit_event()` instead, with its own simpler cooldown standing in for the verifier's confirmation
gate. This is documented inline in `edge/main.py` at the call site, not just here.

**What did NOT change:** the detector, ByteTrack, the Adaptive Compute Gate, the Track Continuity
Guard, the Hybrid Reliability Engine, and the Event Verifier's core logic are all untouched.

**Tests:** `tests/unit/test_preprocessing.py` (7 tests: per-condition gating, real contrast increase
on a synthetic dark frame, no in-place mutation, spatial-dimension preservation for bbox coordinate
validity) and `tests/unit/test_night_motion_fallback.py` (5 tests covering `NightMotionFallback`
itself for the first time — first-frame priming, no-motion-on-identical-frames, real motion detection,
the `min_area` threshold's actual effect, per-instance state isolation). Full suite: 139 pre-existing
+ 12 new = 151 passed, 0 failed, 0 broken.

---

## Priority-Ordered Offline Sync Queue (added — architecture v4 §10, FUTURE-tier item)

**What changed:** `edge/sync/sync_client.py`'s SQLite outbox gained a `severity_rank` column, populated
at `enqueue()` time from the `EvidencePackage.severity` field already being packaged (`HIGH`→3,
`MEDIUM`→2, `LOW`→1, missing/unrecognized→0). `_fetch_pending()`'s ordering changed from
`sequence_number ASC` to `severity_rank DESC, sequence_number ASC` — a HIGH-severity event queued
behind older LOW-severity ones now syncs first once bandwidth returns; same-severity events still
resolve FIFO by sequence number.

**Why this doesn't threaten chain integrity:** the hash-chain (`edge/evidence/packager.py`) is a
strictly sequential, append-only *local* ledger tied together by each record's embedded
`previous_hash` — verified independently of arrival order at the backend (confirmed by inspection:
`backend/api/events.py::ingest_event` stores each event keyed by its own fields, with no dependency on
receiving events in sequence order). Chain order and network delivery order are two different things;
only the former needs to be strictly sequential, and this change only ever touches the latter.

**A real migration bug caught before it shipped:** the first version added the new
`idx_queue_priority` index in the same schema script as the table creation — for a *pre-existing*
database (`CREATE TABLE IF NOT EXISTS` is a no-op against one), the index would be created against a
`severity_rank` column that didn't exist yet, since the ALTER TABLE migration ran *after* the schema
script. Fixed by splitting table creation and index creation into two separate scripts with the
migration guard run strictly between them.

**Validated against real, pre-existing data, not just synthetic tests:** `edge/data/sync.db` already
exists in this repository from an actual prior run (`edge/data/clips/` holds real captured JPEGs dated
2026-09-01) — and it has the *old* schema, no `severity_rank` column. Running the migration against a
copy of this real file confirmed it works cleanly: **8,578 queued (never-synced) events**, a real
backlog from that prior run. Two things worth the team's attention, found while verifying this, not
part of what this change fixes:
- That 8,578-deep backlog suggests sync to a backend never actually succeeded during that run — worth
  checking before assuming the store-and-forward path has been exercised against a live backend.
- The JPEGs in `edge/data/clips/` from that run predate the AES-256 encryption change (a few turns
  ago) and are plain, unencrypted files — evidence captured *before* that change is not retroactively
  encrypted, only evidence captured after it. Both noted in `docs/LIMITATIONS.md`.

**What did NOT change:** `sync_once()`'s "stop the batch on first upload failure" behavior is
unchanged — now applied to the priority-ordered result set (documented inline at the call site so a
future reader doesn't mistake the reordering for also having revisited that decision).
`EvidenceChainStore`, `EvidencePackager`, and the backend ingestion endpoint are all untouched.

**Tests:** `tests/unit/test_sync_client_priority.py` (11 tests: rank ordering, same-severity tie
breaking, missing-severity handling, migration against a hand-built legacy-schema database, migration
idempotency, queue-depth correctness). Full suite: 151 pre-existing + 11 new = 162 passed, 0 failed,
0 broken.

---

## Backend Decrypt-on-View for Encrypted Evidence (added — architecture v4 §10)

**What changed — four pieces:**

1. **`shared/crypto.py` (new)** — the AES-256-GCM primitives from `EvidenceEncryptor` (edge) were
   extracted here so the backend doesn't duplicate cipher logic. `EvidenceEncryptor.encrypt()`/
   `.decrypt()` now delegate to this module; its public API and behavior are unchanged (verified: all
   28 pre-existing `test_evidence.py` tests still pass unmodified).
2. **`backend/security/evidence_key_wrap.py` (new)** — wraps a camera's raw AES key with a
   server-derived key-encryption-key (KEK) before storage. The KEK is derived via HKDF from
   `settings.SECRET_KEY` with a domain-separation label — deliberately **not** `SECRET_KEY` reused
   directly, since reusing one secret for two different cryptographic purposes (JWT signing there,
   key-wrapping here) is a real anti-pattern this avoids.
3. **`PUT /cameras/{camera_id}/evidence-key`** (`backend/api/cameras.py`, ADMIN-gated, mirrors the
   existing `PUT /cameras/{id}/public-key` pattern exactly) — accepts a camera's raw AES key
   (base64), wraps it, stores it in a new `Camera.evidence_key_wrapped` column. The raw key is never
   persisted. `EvidenceEncryptor.get_raw_key_b64()` (new) and `scripts/upload_evidence_key.py` (new)
   make this actually usable, not just theoretical.
4. **`GET /events/{event_id}/evidence-image`** (`backend/api/events.py`, requires `require_any_role`)
   — reads the evidence file, decrypts it if it's a `.jpg.enc` (using the requesting event's camera's
   unwrapped key) or serves it as-is if it's a legacy plain `.jpg`, and returns it as an image
   response.

**The architectural constraint this is honest about, not silent on:** `Event.evidence_clip_ref`
(`shared/schemas.py`) has always been a local **file path string**, not the image bytes — edge sync
(`edge/sync/sync_client.py`) never transmits the actual snapshot to the backend, only this path. The
new endpoint can only read that path because, in this project's current single-machine deployment, the
backend and edge process share a filesystem. **A real distributed deployment, where the edge device
and backend run on different machines, would need the edge to actually upload the evidence bytes
during sync — that is a separate, larger change, not implemented here.** This is documented at the
call site in code and in `docs/LIMITATIONS.md`, not glossed over.

**Two real pre-existing databases needed a migration, found by inspecting actual repo state, not
assumed:**
- `D:\SIH\netraksh\netraksh.db` already has a `cameras` table (1 real row: `edge-001`/"Alpha Gate")
  from before this change — `Base.metadata.create_all()` never alters an existing table, so this
  column would silently not exist there. Fixed with a new `_migrate_add_missing_columns()` in
  `backend/database/session.py`, using SQLAlchemy's database-agnostic `inspect()` (not SQLite-only
  `PRAGMA`, since `DATABASE_URL` can point at Postgres or SQLite) — called from `init_db()` on every
  startup, a no-op once the column exists. **Verified against a copy of the real file**, not just a
  synthetic one: column added, the existing camera row preserved.
- `edge/data/sync.db` (already migrated last turn) has real, pre-existing legacy `.jpg` snapshots
  referenced by its queued events — exactly the "legacy plain JPEG" case `get_evidence_image()`
  explicitly handles, not a hypothetical.

**A real pre-existing gap noticed while doing this, not fixed here (out of scope):**
`GET /events/{event_id}` (`get_event`, just above the new endpoint) has **no auth dependency at
all** — currently readable by anyone unauthenticated. The new `get_evidence_image()` deliberately
requires `require_any_role` rather than silently matching that weaker pattern; the pre-existing gap on
`get_event` is called out in code and in `docs/LIMITATIONS.md` for the team to decide on, not silently
left undocumented.

**What did NOT change:** `EvidencePackager`, `EdgeKeyManager`, the edge sync client's transmission
format, and every other endpoint are untouched. `EvidenceEncryptor`'s external behavior is identical
pre/post-refactor.

**Tests:** `tests/unit/test_shared_crypto.py` (7 tests: round-trip, nonce uniqueness, tamper/wrong-key
detection — the same guarantees `test_evidence.py`'s `TestEvidenceEncryptor` already covered, now
verified at the shared-primitive level too), `tests/unit/test_evidence_key_wrap.py` (9 tests:
wrap/unwrap round-trip, tamper detection, and specifically that the KEK is a real HKDF derivation, not
`SECRET_KEY` reused naively), `tests/unit/test_db_migration.py` (4 tests against a hand-built
legacy-schema table: column added, rows preserved, idempotent, no-op on a brand-new database). Full
suite: 162 pre-existing + 20 new = 182 passed, 0 failed, 0 broken. Endpoint-level HTTP tests
(`PUT .../evidence-key`, `GET .../evidence-image`) are **not** covered by an automated test in this
pass — `tests/integration/` and `tests/e2e/` are empty for every existing endpoint in this codebase,
not just these two, and building a FastAPI `TestClient` + auth-fixture harness from scratch is a
separate, larger effort than this feature. The pure functions each endpoint depends on (crypto,
wrapping, migration) are fully covered; the HTTP wiring itself is not — noted honestly rather than
implied as tested.

---

## Zone Coordinate Normalization + Populated Demo Zones (added — real bug fix, not aspirational)

**The actual request was "populate zones_config.json with real coordinates."** No demo video file
exists anywhere in this repository, and the default video source is a live webcam
(`VIDEO_SOURCE=0`), not a file — so there was no real footage to derive genuine coordinates from, and
writing plausible-looking pixel values against a guessed resolution would have been exactly the kind
of invented number this project has been careful to avoid everywhere else. Checking why zone
coordinates even needed a specific resolution at all surfaced a real, separate bug worth fixing
first.

**The bug:** `VirtualFenceModule.check()` in `edge/rules/modules.py` carried a comment claiming zone
polygons use normalized 0-1 coordinates, but the code beneath it never normalized anything — it
compared a track's raw-pixel centroid directly against whatever units the config file's polygon
happened to be written in. A zone config authored for one camera's resolution would silently
misbehave (fire in the wrong place, or never fire) on any other resolution. This affected every
zone-matching module identically: `VirtualFenceModule`, `LineCrossingModule`, `BehaviorModule`
(loitering + abandoned-object's zone lookup), `ANPRModule`, and `FaceDetectionModule`.

**The fix:** a new `normalize_point()` helper divides a raw-pixel point by the current frame's real
`(width, height)` before every polygon test. `edge/main.py` computes `frame.shape[:2]` once per frame
and passes it to `behavior_module.update()`, `fence_module.check()`, and `line_module.check()`;
`ANPRModule.process()` and `FaceDetectionModule.detect()` already received the frame directly and now
derive the same dimensions from it. All five call sites' new parameters default to `1.0, 1.0` (a
no-op divide) when omitted — every one of the 17 existing call sites across `test_line_crossing.py`
required zero changes as a result; the default made them keep testing exactly what they tested before
(coordinates in an arbitrary, self-consistent unit), while the live pipeline in `edge/main.py` always
passes the real frame size.

**Consequence — zone config is now resolution-independent by design:** a polygon written once (by
clicking real points, see below) keeps working correctly regardless of what camera or resolution
actually ends up in the demo — this was the actual uncertainty behind the original request (webcam vs.
video file, unknown resolution), solved by removing the dependency on knowing it in advance, not by
guessing at it.

**`demo/scripts/zones_config.json` is now populated** with one zone of each type (fence, boundary/line,
checkpoint, verification) in normalized coordinates, explicitly labeled in a `_readme` field (a key
`load_zones()` already ignores) as illustrative placeholders, not measured against real footage.

**`scripts/define_zone.py` (new)** is how these become genuinely real: it grabs one frame from an
actual camera or video file, opens a click-to-place-points window, and writes the resulting polygon
into `zones_config.json` in the exact normalized format the pipeline expects — replacing a
placeholder zone by `zone_id` or adding a new one, leaving every other zone untouched. This is the
only way to get real coordinates without fabricating them.

**What did NOT change:** the point-in-polygon and line-side-test algorithms themselves, the Event
Verifier, the Hybrid Reliability Engine, and every other module downstream of these five call sites
are untouched — this is purely a "what unit are these numbers in" fix at the boundary.

**Tests:** `tests/unit/test_zone_normalization.py` (6 tests, including an end-to-end test proving a
zone fires correctly at 720p and 1080p from the *same* normalized config, and does NOT fire on the
same raw pixel region at the wrong resolution — the actual bug this fixes, demonstrated, not just
asserted) and `tests/unit/test_define_zone.py` (13 tests covering every pure function in the new
script — pixel-to-normalized conversion, zone-record construction, config upsert-by-id, point-count
validation — including one that round-trips the script's output through the real `load_zones()`, not
a mock). The interactive click-loop itself needs a real display and is not covered by an automated
test — noted rather than silently skipped. Full suite: 182 pre-existing + 6 new
(`test_zone_normalization.py`) + 13 new (`test_define_zone.py`) = 201 passed, 0 failed, 0 broken;
**zero existing tests required modification**.

---

## Real Before/After False-Positive Measurement (architecture v4 §11, run for real)

**What was done:** no demo video or staged scenario existed to test against, so
`demo/videos/vtest.avi` — OpenCV's own official sample pedestrian-tracking clip (768×576, 10fps,
795 frames), fetched from `github.com/opencv/opencv` — was downloaded as a stand-in and inspected
frame-by-frame to place a real fence zone over its actual visible walkway (not a placeholder). A new
`scripts/run_false_positive_benchmark.py` runs the real production classes (`CameraHealthMonitor`,
`SceneConditionClassifier`, `CalibrationModule`, `DetectionTracker`/YOLO, `VirtualFenceModule`,
`make_reliability_decision`, `EventVerifier`, `PipelineMetrics`) against this clip twice — once with
the Event Verifier's confirmation requirement relaxed to 1, once at the shipped default of 3 — and the
real counts and latencies were transcribed into `docs/PERFORMANCE_REPORT.md`.

**A real bug caught mid-run, not after:** the first version of the benchmark harness omitted the
"pending re-check" loop that `edge/main.py` uses to let a multi-confirmation fence-crossing candidate
accumulate confirmations across frames (`VirtualFenceModule.check()` only fires once, on the crossing
transition — subsequent confirmation requires separately polling `get_track_zone()`). Without it, no
candidate could mathematically ever reach 3 confirmations regardless of what was in the video — the
first run's "0 alerts" result was an artifact of an incomplete harness, not a finding about the
pipeline, and was corrected before being reported anywhere.

**The honest result, after the fix:** 52 raw fence-crossing candidates fired; 23 became alerts under
*both* policies (1-confirmation and the shipped 3-confirmation default) — identical. This is **not**
the "verification reduces false alarms" headline number a team might hope for, and `docs/
PERFORMANCE_REPORT.md` reports it exactly that plainly rather than reframing it. What the same run
does show, diagnosed rather than glossed over: the Hybrid Reliability Engine independently filtered
52→23 candidates (only 23 ever reached `R≥0.75` on any frame), and every one of those 23 stayed
reliably detected for 3+ consecutive frames — this specific clean daytime clip simply contains none of
the single-frame tracking jitter the Event Verifier exists to catch, so it cost nothing but also
proved nothing here. Real latency numbers (mean 44.6ms/frame, P95 49.2ms, ~21.8 FPS on CPU) and
resource usage (~410–430MB RSS; the CPU% reading was found not to be credible and is flagged as such,
not reported as if it were) are in the same file.

**What did NOT change:** no production code — this is a new, standalone, read-only measurement script
that does not touch `EvidencePackager`, `SyncClient`, or write any certs/DB files; `edge/main.py` and
every module it calls are untouched.

**Explicitly flagged as incomplete, not silently left out:** this run used a generic public test clip,
not the team's actual demo footage or a staged intrusion scenario, and does not cover night/fog/glare
conditions or event-level (evidence-packaging) latency. `docs/PERFORMANCE_REPORT.md` says exactly this
and lists re-running against real staged footage as an explicit open item, checked off as *not* done
in its own honesty checklist.

---

## Frontend Decrypt-on-View Wiring (architecture v4 §10, closes the last open piece)

**What changed:** `frontend/src/pages/Evidence.jsx`'s Media Card now fetches the real decrypted
evidence image from `GET /events/{event_id}/evidence-image` instead of only ever showing the static
`/mock-fence.jpg` placeholder. States handled: `loading`, `ready` (real image rendered), `no-evidence`
(404), `no-key` (409 — camera hasn't run `scripts/upload_evidence_key.py` yet), `auth-required`
(401/403), and `error` (backend unreachable) — each with a distinct, honestly-labeled on-screen state
rather than silently falling back to the mock image indistinguishably from a real one.

**A materially bigger finding than the task looked like:** this frontend had **zero auth
infrastructure** anywhere — no login, no token storage, not a single `Authorization` header sent
anywhere in the codebase (confirmed by inspection: the existing `/verify` call sends no credentials,
which only works because that endpoint has no auth dependency either — a pre-existing gap, not
introduced here, already noted in `docs/LIMITATIONS.md`). The new evidence-image endpoint deliberately
*does* require a valid token (`require_any_role`), so wiring it up required a minimal real login flow,
not just a fetch call:

- **`frontend/src/services/auth.js` (new):** `login()` (POSTs form-encoded credentials to the
  already-existing `POST /auth/token`, which the frontend had never called), `getToken()`/`isAuthenticated()`
  (localStorage), and `authFetch()` (attaches the Bearer token to any request). Kept deliberately
  minimal — no route guarding, no logout UI polish, no token refresh — proportionate to what this task
  needed, not a full auth system.
- An inline sign-in form appears directly in the Media Card the first time a viewer without a token
  tries to view evidence, using the backend's already-seeded default admin account
  (`scripts/init_db.py`) — no new backend code was needed, only a frontend caller for infrastructure
  that already existed.

**What did NOT change:** no backend code. `Evidence.jsx`'s existing `/verify` flow, event list, and
every other page are untouched.

**Tests:** no new automated tests — this is a frontend-only change and the project has no frontend
test suite yet (a pre-existing gap, not introduced here). Verified instead by an actual production
build (`vite build`, 1837 modules, zero errors) and a lint pass (`oxlint`, zero errors — pre-existing
warnings on unrelated lines untouched). The backend's 201 Python tests are unaffected and confirmed
still passing.

---

## Zones Grounded in Real Footage (partial progress on the last open item)

**What changed:** `demo/scripts/zones_config.json`'s four placeholder zones were replaced with
coordinates placed by visually inspecting three real frames (t=30, 200, 450) from
`demo/videos/vtest.avi` — the same clip already used for the real false-positive benchmark
(`docs/PERFORMANCE_REPORT.md`) — instead of arbitrary round-number rectangles. Each zone now
corresponds to something actually visible in the footage: the fence zone covers a real taped-off,
cone-marked area in the scene; the trip-line crosses a real pedestrian chokepoint by a lamppost;
the checkpoint zone covers the only vehicle-parking area in frame; the verification zone covers a
signpost pause-point multiple people are seen stopping near across all three inspected frames.

**Why this isn't the same as running `scripts/define_zone.py` for real, and the task wasn't silently
substituted:** that script requires a live GUI window and real mouse clicks from a human operator —
there is no way to drive that interactively from here. Rather than leave the zones as ungrounded
placeholders or silently do something different without saying so, the same "inspect a real frame,
place a zone against real visible content" principle the script encodes was applied by hand, using
the one real video available. This is a genuine improvement in grounding, not a substitute for the
real thing — see `docs/LIMITATIONS.md`.

**Verified as actually active, not just plausible-looking:** ran `scripts/run_false_positive_benchmark.py`
against the new `fence-perimeter-1` coordinates on the real clip — 36 real candidate crossings fired
across 795 frames (23 alerts after Reliability Gate filtering, matching the same pattern already
documented in `docs/PERFORMANCE_REPORT.md`). A zone that never fires would have been a silent dead
end; this one is confirmed live.

**What did NOT change:** no code — this is a data-file update only. `edge/rules/modules.py`,
`scripts/define_zone.py` itself, and every test are untouched; the full 201-test suite is unaffected
and confirmed still passing.

---

## Reliability Panel Wired to Real Backend Data

**What changed:** `frontend/src/pages/Dashboard.jsx`'s "Reliability Decision" panel previously showed
entirely hardcoded values (`STREAM ACTIVE`, `FPS 30.0 (STABLE)`, `NIGHT / LOW-LIGHT`, `AI CONFIDENCE
0.91` / `NIGHT THRESHOLD 0.82`) regardless of what — if anything — was actually happening, and the
`[DETECTED]` button at the bottom was static markup, not tied to `decision_state` at all. It now
parses the real `decision_reason` string `edge/reliability/decision.py` writes (already flowing over
the existing `/ws/dashboard` WebSocket via `EventResponse` — no backend change needed) and renders the
actual D/T/S/H factors, the real R score, the real 0.75 threshold, and a DEGRADED-camera flag exactly
when the backend actually set one. Gate 1 shows the real `camera_health_state`; Gate 2 shows the real
`scene_condition`. When no real event has arrived yet, every panel honestly shows "Waiting for a real
event…" instead of a plausible-looking fabricated number — matching this project's standing rule
against ever displaying a number that didn't come from somewhere real.

**A relabeling this required, and why it's not scope creep:** the old panel's third box was titled
"Calibrated Conf" with a hardcoded "NIGHT THRESHOLD" field — vocabulary from the pre-Hybrid-Engine
3-gate cascade this project moved away from several changes ago. Since this panel is the exact one
`docs/PERFORMANCE_REPORT.md`'s Field Guide script plans to show a judge (Demo Segment A), leaving
stale, inaccurate architecture language on it while wiring in real numbers next to it would have been
worse than the old fully-fake version. It's now labeled "Reliability Factors (R = 0.40·D + 0.20·T +
0.20·S + 0.20·H)" — the actual formula, not a description of the old design.

**Verified end-to-end against the real backend, not just visually inspected:** started the actual
`backend.main:app` (serving the real, already-built `frontend/dist/`) via a new `.claude/launch.json`,
confirmed the real database migration log line, then POSTed a realistic event through the real
`POST /events` ingestion endpoint with `decision_reason="R_ABOVE_THRESHOLD_DEGRADED_CAMERA:R=0.812
>=0.750 (D=0.80,T=0.85,S=0.63,H=0.50),health=excessive_blur"` and confirmed in a live screenshot that
the dashboard rendered exactly D=0.80/T=0.85/S=0.63/H=0.50, R=0.812, threshold=0.750, the DEGRADED
flag, and the DETECTED button — all parsed correctly from the real string, not hand-verified against
the regex alone. The synthetic test event was deleted from the real database afterward.

**What did NOT change:** no backend code — every field this panel now uses was already in
`EventResponse` and already being broadcast; this was a frontend-only rewiring.

**Tests:** no new automated tests (frontend has no test suite yet, a pre-existing gap). Verified via
a real `vite build` (zero errors), `oxlint` (only pre-existing warnings on lines not touched by this
change), and the live end-to-end POST-and-screenshot check above. Backend's 201 tests unaffected and
confirmed still passing.

---

## Pre-Deployment Hardening: Auth Gaps Closed + Route Collision Fixed

Prompted by the move toward putting a live instance in front of judges — this is a first pass at
closing gaps that were fine for a local single-user demo but not for anything public.

**What changed:**
- `GET /events/{event_id}` and `POST /events/{event_id}/verify` (`backend/api/events.py`) now require
  `require_any_role`, matching `GET /events/{id}/evidence-image`. Both had been documented as open
  gaps in `docs/LIMITATIONS.md` since the evidence-image endpoint was added.
- Fixing the `/verify` endpoint's auth surfaced two independent, pre-existing frontend bugs in the same
  `handleVerify()` function (`frontend/src/pages/Evidence.jsx`) — neither related to auth, both just
  never caught because nothing had exercised this path end-to-end before:
  1. It called the endpoint with a bare `fetch()` (defaults to `GET`); the real route is `POST`. Every
     click had been silently 405'ing straight into the `catch` block since this button was written.
  2. Even on a successful call, it read `data.is_valid`, a field `VerificationResponse` doesn't have
     (the real fields are `hash_valid`/`signature_valid`/`chain_valid`) — so a genuinely valid
     verification would still have displayed "failed".
  Fixed to `authFetch(..., { method: 'POST' })` and to check all three real boolean fields.
- The frontend's `/health` SPA route (Camera Health Matrix page) was renamed to `/camera-health`. It
  collided with the backend's `GET /health` liveness probe (`backend/api/system.py`) — a real hosting
  platform polls exactly that path for container health checks, and FastAPI's own route always wins
  over the SPA catch-all on a direct/hard navigation, so `/health` served raw liveness JSON instead of
  the page. The backend's `/health` route itself is untouched.

**What did NOT change:** `GET /events` (`list_events`) still has no auth dependency — left open
deliberately, see `docs/LIMITATIONS.md`, since the dashboard's live feed depending on it is a product
decision (should unauthenticated viewers see live events at all?), not a drive-by fix. No database
schema changes. No changes to the reliability/temporal/evidence pipeline.

**Verified:** full backend suite still 201/201 passing. Rebuilt frontend (zero errors), `oxlint` clean
(pre-existing warnings only). Verified live in-browser: hit `/evidence` unauthenticated → correctly
shown the "Sign in to view evidence" state (not a raw 401); logged in as the seeded `admin` account;
clicked "Verify Netraksh Integrity Chain" and confirmed via `read_network_requests` that the request is
now a `POST` (previously never fired as one) carrying the `Authorization` header, returning `404` for
the mock/placeholder event ID shown by the page's fallback display data (expected — that ID has no
real database row) rather than the old silent `catch`-block failure.

**Tests:** no new automated frontend tests (pre-existing gap, frontend has no test suite). Backend
auth enforcement on these two routes is exercised the same way `get_evidence_image`'s was — no
dedicated HTTP-level test yet (see `docs/LIMITATIONS.md` §2, "Endpoint-level HTTP tests... do not
exist").

---

## Pre-Deployment Hardening: Hardcoded `localhost:8443` Removed

**What changed:** every frontend file talked to the backend via a literal `http://localhost:8443` or
`ws://localhost:8443` string — 10 call sites across `services/auth.js`, `pages/Health.jsx`,
`pages/Evidence.jsx`, `pages/Dashboard.jsx`, `pages/Alerts.jsx`, `components/Header.jsx`, and
`components/DemoSidebar.jsx`. That's harmless while the app is only ever opened as
`http://localhost:8443` (the backend serves the built frontend from that same origin — see
`backend/main.py`'s `StaticFiles` mount), but it would silently break every fetch and the dashboard's
live WebSocket the moment the app is reached at any other origin (a deployed domain, a different port,
`https://`). `services/auth.js` now exports `BACKEND_URL = window.location.origin` and
`WS_URL` (protocol-aware: `wss://` under `https:`, `ws://` otherwise) computed from the page's own
location at runtime, and every call site imports one of the two instead of hardcoding a string. No
build-time environment variable needed — this resolves correctly under `localhost` today and under
whatever real domain the app is deployed to next, automatically.

**Also fixed while here:** `Header.jsx`'s periodic `/sync/status` poll was a bare `fetch()` with no
Authorization header, against an endpoint that requires `require_any_role` — it had always 401'd
silently (caught, ignored) for any viewer, logged in or not. Switched to `authFetch()`, so it now
actually succeeds once a viewer has signed in via the Evidence page's login form.

**Confirmed, not assumed, still real:** `DemoSidebar.jsx`'s "Demo Scenario Control" panel calls
`/demo/inject-condition`, `/demo/trigger-camera-failure`, `/demo/simulate-offline` — grepped the entire
backend and confirmed none of these routes exist anywhere. Every click has always silently fallen
through to the `catch` block's local-only UI state. This was already honestly disclosed in the UI
itself (each button carries a "Simulated" badge, visible in the live screenshots) — not a hidden gap,
just an unimplemented one, now called out explicitly here and in `docs/LIMITATIONS.md` rather than left
merely "not yet inspected."

**Verified:** full backend suite 201/201. Rebuilt frontend (zero errors), `oxlint` clean (pre-existing
warnings only). Verified live: reloaded the app from a fresh browser tab, confirmed via
`read_network_requests`/console that the relative `WS_URL` still connects, then POSTed a real
synthetic event through `POST /events` and confirmed via live screenshot that it arrived over the
WebSocket and rendered correctly (Gate 1 OK, Gate 2 Clear Day, Gate 3 D/T/S/H=0.90) — the URL change
did not silently break the live event path. Test event deleted from the real database afterward.

---

## Frontend Audit + Full Real-Data Wiring Pass

Prompted by "check each and everything, all the functions in the frontend fully working... or no?"
followed by "make the project more and more advanced and fully workable/functionable" — a systematic
audit of every page, button, and fetch call in the frontend, then a full pass fixing everything
unambiguous. This is the largest single change in the project's history in terms of files touched;
full detail is broken out by area below.

### 1. Camera Health Matrix — was 100% mock, now genuinely real end-to-end

This was the single biggest gap found. `GET /cameras` (`backend/api/cameras.py`) already existed and
returned real `health_state`/`fps_actual`/`drift_seconds` — but `frontend/src/pages/Health.jsx` never
called it, running instead on 3 hardcoded cameras (CAM-07/12/04) with a "82%" / "36 OK / 5 DEGRADED /
3 FAILED" summary that didn't even arithmetically match the 3 cameras shown below it. Investigating
further surfaced that **the gap went deeper than the frontend**: no backend code path had ever
written a single row to the `CameraHealth` table, despite `edge/health/camera_health.py`'s
`CameraHealthMonitor` computing real blur/exposure/FPS/drift values every frame. The reason: the
"periodic health heartbeat" `edge/main.py`'s own docstring described didn't exist — `last_health_report_time`
was threaded through `_process_frame()`'s signature every frame but never actually read there, a dead
timer implying behavior that was never implemented.

**What changed, end to end:**
- `edge/main.py`: added `_report_camera_health()`, called from the (now-live) 5-second timer in
  `_run_frame_loop()`. Best-effort POST of the real `CameraHealthReport` to the backend — never
  interrupts the frame loop on failure, same offline-tolerant posture as `SyncClient`. This is
  deliberately NOT routed through the offline sync queue: it's a heartbeat, not evidence — losing one
  is fine, the next is 5 seconds away.
- `backend/api/cameras.py`: new `POST /cameras/{id}/health` endpoint — writes the real `CameraHealth`
  row and broadcasts it over `/ws/dashboard` via `broadcast_camera_health()`, a function that has
  existed since early in this project but had never once been called by anything.
- `shared/schemas.py`: widened `CameraStatusResponse` with `fps_declared`/`blur_score`/
  `exposure_clip_fraction` — real fields `CameraHealth` already stored but never exposed via the API.
- **A real, previously-latent bug found and fixed in the same pass:** `_camera_to_response()` fell back
  to the literal string `"UNKNOWN"` for `health_state` when a camera had no health row yet — but
  `CameraHealthState` is a strict enum of only `OK`/`DEGRADED`/`FAILED`. This made `GET /cameras`
  **500 for every real camera in the database**, always, from the moment it was written, since no
  camera had ever had a health row before this change either. Fixed by making `health_state: Optional`
  and passing `None` instead of a fabricated enum value — caught only because this session was the
  first time anything actually called this endpoint end-to-end with real data.
- `frontend/src/pages/Health.jsx`: fully rewritten. Real `GET /cameras` fetch (auth-gated, same
  `LoginPrompt` pattern as Evidence.jsx — see below), live WS merge (now genuinely reachable), real
  "System Sight" percentage computed from the real fleet, working "All Sectors"/"Needs Attention"
  filters (previously two `<button>`s with no `onClick` at all), and an honest "NO DATA YET" state per
  camera instead of ever fabricating a reading. The "⟲ INITIATE REBOOT" button — no backend endpoint
  exists for it — is left visible but `disabled`, with a tooltip explaining why, rather than either
  removed or left silently doing nothing on click.

**Verified live, not just read:** POSTed a real health report via `POST /cameras/{id}/health` (hit the
500 bug first, fixed it, then confirmed 201 + real DB row), confirmed `GET /cameras` returns it,
logged into the page via the new `LoginPrompt`, confirmed the real FPS/blur/exposure/drift numbers
render, confirmed the "Needs Attention" filter actually hides the OK camera, then deleted the test row.

### 2. Evidence Vault — remaining fake bits closed out

- Extracted the inline login form (previously duplicated verbatim inline) into a shared
  `frontend/src/components/LoginPrompt.jsx`, now used by both Evidence.jsx and Health.jsx.
- Search box had no `onChange` at all — typing did nothing. Now filters the real event list by
  `event_id`/`hash`/`event_type`/`decision_state`. (Caught during live verification: an initial version
  matched only `event_id`/`hash`, literally what the placeholder text promises, but a real user typing
  "Perimeter" — visible right there in the list — reasonably expects a match; broadened accordingly.)
- The "Cryptographic Hash Verification" strip showed the literal hardcoded strings `"RAW: 1.4MB"` and
  `"A94F...72C1"` for every single event, real or not. Now shows the real decrypted-evidence byte size
  (captured from the actual fetched blob) and the real `EventResponse.hash`, truncated for display —
  or an honest `"NO FILE"`/`"PENDING"` when neither exists yet.
- The event-list "SIGNED" badge was a hardcoded label. Now reads the real `signature` field
  (`SIGNED`/`UNSIGNED`) — the mock placeholder events correctly now show `UNSIGNED`, since they aren't.

### 3. Cross-Command Alerts — was real WS data permanently polluted with fake alerts

`GET /alerts` (real, RBAC-gated) existed and was never called; the page ran only on live WS pushes
(`new_alert`), permanently concatenated with 2 hardcoded fake alerts ("Multiple Armed Intruders",
"Vehicle Ramming Attempt") rendered identically to real ones, with zero visual distinction.

**What changed:**
- `Alerts.jsx` now fetches `GET /alerts` on load and merges it with live WS pushes (deduped by
  `alert_id`) — same convention Evidence.jsx already used for its own mock fallback: the 2 demo alerts
  now only appear when there are zero real alerts, clearly labeled `DEMO`.
- `AlertResponse` (`shared/schemas.py`) had no camera/event-type/timing fields at all — only
  severity/jurisdiction/blockchain/ack fields. Widened with `camera_id`/`event_type`/`zone_id`/
  `created_at`, sourced from `Alert.event` (an ORM relationship that already existed) — this is what
  lets the page show a real derived title ("HIGH — Abandoned Object") and real camera/elapsed-time
  instead of nothing. `backend/services/escalation.py`'s live WS broadcast payload was widened the same
  way for parity between the REST and WS paths.
- The real `POST /alerts/{id}/acknowledge` endpoint existed with no UI control anywhere. Added an
  "Acknowledge" button, wired to the real endpoint, using the seeded admin's session.
- **A second `/health`-class route collision found and fixed:** the frontend's `/alerts` SPA route
  collided with the real backend route `GET /alerts` (`backend/api/alerts.py`) — a direct
  hard-navigation to `/alerts` returned `{"detail":"Not authenticated"}` JSON instead of the page, for
  the identical reason `/health` did two changes ago. Missed when fixing `/health`, because nothing
  had checked every other frontend route against every other backend prefix at the time. Renamed to
  `/cross-command-alerts`; this session then audited every remaining frontend route against every
  backend router prefix to confirm no others collide.
- The tactical map view remains intentionally decorative — there is no real-world lat/lon or geodata
  model anywhere in this project (zones are 0-1 normalized within one camera's own frame, not a map).
  Left as-is, now explicitly labeled "(illustrative)" rather than silently implying real geodata.

**Verified live:** logged in, hit `/cross-command-alerts` directly (confirmed the collision first,
then confirmed the fix), saw 9 real alerts render with real derived titles/cameras/elapsed-time,
clicked Acknowledge on one, confirmed via `read_network_requests` a real `200 OK` to
`POST /alerts/{id}/acknowledge`, and confirmed the header's alert-count badge dropped 09→08 live in
response — a real cross-page side effect, not a local-only UI change. Two orphaned test-artifact
alert rows (from earlier sessions' synthetic testing, confirmed to reference no existing event) were
found and deleted from the real database as part of this verification.

### 4. Dashboard video overlay — dead bbox branch removed

`VideoFeed.jsx` checked `eventData.bbox` to decide whether to show a real detection label — but
`EventResponse` (what actually crosses the WebSocket) has no `bbox` field at all; it exists only on
the edge-internal `EvidencePackage` schema and never reaches the frontend. This branch could never
fire for any real event, so the label always showed the hardcoded "PERSON #184 | 91% CONF" even while
a real `detection_class`/`track_id`/`confidence` sat right there in the same object. Fixed to use the
real fields for the label whenever a real event exists (the box's on-screen position stays a
placeholder — there's no real pixel coordinate to draw it at without an actual video stream, which
this project doesn't have). Verified live: POSTed a real event with `detection_class: 'vehicle'`,
`track_id: 888`, confirmed the overlay updated to "VEHICLE #888 | 88% CONF".

### 5. Header — real alert count

The "⚠ 04" badge was a hardcoded literal, never reflecting anything. `/system/status` already
returned a real `pending_acknowledgements` count; the header just never read it. Now polled every 5s
alongside the existing sync-status poll, shown as `--` (not `00`) before the first successful fetch so
"no data yet" is never confused with "zero alerts".

**What did NOT change:** `GET /events` (`list_events`) still has no auth dependency — this remains a
deliberate open gap, same reasoning as before (see `docs/LIMITATIONS.md`). No changes to the edge
detection/reliability/temporal/evidence pipeline. The "Demo Scenario Control" panel's four buttons
remain unimplemented (no backend routes exist for them) — already honestly labeled "Simulated" in the
UI; building real scenario injection is a modest but real separate feature, not attempted here.

**Tests:** backend suite 201/201 passing throughout every step of this pass. No new backend HTTP-level
tests were added for the new `POST /cameras/{id}/health` endpoint (same pre-existing gap as every other
endpoint in this codebase — see `docs/LIMITATIONS.md` §2); verified instead via live POST + real DB
read + live screenshot, the same method used throughout this project for exactly this kind of check.
Frontend has no test suite (pre-existing gap); verified via `vite build` (zero errors each time),
`oxlint` (36 warnings throughout, all pre-existing patterns already present elsewhere in the codebase —
no new warning class introduced), and extensive live browser verification of every single fix in this
pass, documented above per area.

---

## Render Deployment Prep

Prompted by "let's deploy it live." This is the concrete build/config work needed before a
real deploy — not the deploy itself, which needs the user's own GitHub/Render accounts (see
`docs/DEPLOYMENT.md` for the full walkthrough and what to do next).

**What changed:**
- `backend/config.py`: `DATABASE_URL` now normalizes the legacy `postgres://` scheme to
  `postgresql://` via a `field_validator`. Render (and Heroku-style platforms before it)
  hand out connection strings with the old scheme; SQLAlchemy 1.4+ rejects it outright.
  Without this, pasting Render's own connection string into the env var would crash at
  engine creation on first boot. New test: `tests/unit/test_backend_config.py`.
- `requirements-backend.txt` (new): a verified-minimal dependency set for the backend
  container. The original `requirements.txt` installs the full stack (edge's
  `ultralytics`/`opencv`/`easyocr`/`retina-face` included) because local dev runs
  everything from one Python environment — but the backend container only ever runs
  `backend.main:app`, which never imports edge code at all (confirmed by grepping every
  `from edge`/`import edge` in `backend/` — none exist). Verified, not assumed: built a
  throwaway venv, installed only `requirements-backend.txt`, successfully imported
  `backend.main`, then deleted the venv.
- `Dockerfile`: rewritten to use `requirements-backend.txt`, drop the `edge/` and
  `yolov8n.pt` copies (unused, per above), and drop the `libgl1`/`libglib2.0-0` system
  packages (were only needed for opencv/ultralytics, no longer installed in this image).
  The previous Dockerfile had never been built even once — Docker is unavailable on the
  dev machine this project was built on — so this rewrite is itself unverified by an
  actual `docker build`, same caveat as before, now on a smaller, more carefully-reasoned
  image.
- `render.yaml` (new): a Render Blueprint defining the web service (Docker, free plan,
  `healthCheckPath: /health`) and a managed Postgres database, wired together via
  `fromDatabase`. `SECRET_KEY`/`ADMIN_PASSWORD`/`INITIAL_OPERATOR_PASSWORD`/
  `INITIAL_AUDITOR_PASSWORD` use Render's `generateValue: true` — real random values
  generated at deploy time, never the `CHANGE_ME_*` placeholders this project defaults to
  locally, and never committed to source control.
- `docs/DEPLOYMENT.md` (new): the actual step-by-step walkthrough, including what this
  deployment deliberately does NOT include (the edge pipeline, a real blockchain network)
  and why.

**What did NOT change:** no application logic, no API behavior, no frontend code. This is
pure deployment configuration.

**Honestly unverified:** the Postgres code path itself (`psycopg2-binary`, the connection
pooling settings in `backend/database/session.py`, `init_db()`'s migration logic against a
real Postgres rather than SQLite) has never been exercised against a real running Postgres
server — every verification in this project to date has been against real SQLite, because
that's what's available locally. The schema/migration code is written to be
database-agnostic (SQLAlchemy's `inspect()`, not raw SQLite pragmas), but "written to be"
and "verified to be" are different claims, and this document tries never to blur them.

**Tests:** 204/204 passing (3 new, for the `DATABASE_URL` normalization). Confirmed the
running dev server still boots cleanly after the `backend/config.py` change.

---

## First Real Deploy Attempt: Found a Genuine Production Crash

The first actual Render deploy (database provisioned fine; web service failed) — the real
payoff of everything above being untestable locally without Docker: this is a bug that
only exists once real infrastructure is involved, and it was caught immediately rather
than discovered by a judge.

**The crash, from the real Render build logs:**
```
AttributeError: module 'bcrypt' has no attribute '__about__'
...
ValueError: password cannot be longer than 72 bytes, truncate manually if necessary
```
crashing inside `bootstrap_users()` at startup — the whole app failed to boot.

**Two distinct real bugs, both fixed:**
1. **`bcrypt` 4.1+ removed the `__about__.__version__` attribute** that `passlib`'s
   backend-detection code reads. `passlib[bcrypt]>=1.7.4` doesn't pin `bcrypt` itself, so
   it resolved to whatever the latest version was at Render's build time — newer than the
   `bcrypt==4.0.1` this dev machine happened to already have installed, which is exactly
   why this was invisible locally. Fixed: pinned `bcrypt<4.1` in both `requirements.txt`
   and `requirements-backend.txt`.
2. **`render.yaml`'s `ADMIN_PASSWORD: generateValue: true` produces a random string long
   enough to exceed bcrypt's hard 72-byte limit** — and `bcrypt`'s 4.x line raises
   `ValueError` instead of silently truncating like older versions did. This isn't only a
   Render-generated-secret problem: any real user setting a sufficiently long real
   password would hit the identical crash. Fixed in `backend/security/auth.py`: both
   `hash_password()` and `verify_password()` now truncate to 72 bytes (at a valid UTF-8
   boundary) before ever reaching bcrypt — every password this app touches (login,
   registration, bootstrap) goes through these two functions, so this is a single,
   complete fix, not a patch on one call site.

**Verified, not just reasoned about:** reproduced the exact failure locally first
(`secrets.token_urlsafe(64)` → the same `ValueError`), confirmed the fix resolves it, then
built a second throwaway venv installing the newly-pinned `requirements-backend.txt` from
scratch and confirmed `bcrypt.__about__.__version__` is now present and
`backend.main` imports cleanly. New tests: `tests/unit/test_password_hashing.py`.

**Tests:** 207/207 passing (3 new).

---

## Real Data on the Live Deployment + a Timezone Bug Found While Seeding It

Prompted by "seed some realistic demo events" for the live Render deployment so it doesn't
show empty states on first load for judges.

**What changed:** `POST /events` and `POST /cameras/{id}/health` — the same real, public
endpoints a real edge device uses — were called with 6 varied demo events (different
cameras, severities, decision states, scene conditions, one deliberately DEGRADED-camera
case) and 2 camera health reports, against the real live Postgres database. Dry-run tested
first against the local dev server (temporarily inserting matching camera/zone rows to
mirror the live deployment's real seed data, all cleaned up afterward) — caught and fixed
a real payload bug this way (`CameraHealthReport` requires `camera_id` in the request body,
not only the URL path) before it ever touched the live deployment.

**A second, more interesting bug, found by actually looking at the live result:** a demo
alert created moments earlier showed "T - 330 MINS" elapsed instead of ~1 minute. 330
minutes is exactly the IST UTC offset (5:30) — not a coincidence. Investigating: every
datetime this backend returns (`Event.timestamp`, `Alert.created_at`, etc.) comes back as a
naive ISO string with no UTC marker (`"2026-09-05T05:21:00"`, not `"...05:21:00Z"`) — even
for a field the client originally sent WITH a `Z` suffix. SQLAlchemy `DateTime` columns
store/return naive Python datetimes regardless of the input's timezone info, and Pydantic
doesn't add a marker back when serializing a naive datetime. Every timestamp in this app is
UTC by convention (every display already labels it "UTC") — but `new Date(str)` on a
marker-less string is parsed as the *browser's local time*, silently shifting every
displayed and elapsed time by that viewer's own UTC offset. For any judge or teammate
viewing this from India, every elapsed-time and clock display in this app was wrong by
exactly 5 hours 30 minutes, and would have stayed invisible on a dev machine that never
happened to test from outside UTC.

**Fixed at the frontend** (`frontend/src/utils/time.js`'s new `parseUtc()`), not by
changing the backend's DB column types or migrating existing data — every timestamp
display in `Dashboard.jsx`, `Evidence.jsx`, and `Alerts.jsx` (both the elapsed-time
calculation and the sort comparator) now routes through it. Also fixed in the same pass,
found while touching this code: `Evidence.jsx`'s event-list timestamp used
`.toLocaleTimeString()` (the viewer's local wall-clock time) immediately followed by the
literal text "UTC" — displaying local time mislabeled as UTC, independent of the naive-
string bug above. Now uses the same UTC-safe formatting as everywhere else in the app.

**Verified, with the actual real numbers, not just re-reasoned about:** captured the real
`created_at` value and real `Date.now()` from the live deployment during diagnosis, then
ran both the old and new parsing logic against those exact real values head-to-head:
331 minutes (reproducing the bug) → 1 minute (correct) after the fix.

**What did NOT change:** the backend's database schema, column types, or any
`datetime.utcnow()` call site — this project's tests already flag that call as deprecated
Python (see the `DeprecationWarning` in every test run), and migrating every `DateTime`
column to `timezone=True` would be the more "correct" long-term fix, but is a materially
larger, riskier change (schema migration across every table with a timestamp) for the
identical practical result this frontend-side fix already achieves, given this app's
timestamps are UTC by convention everywhere already.

**Tests:** no new automated test (this is frontend-only, JS-only logic — the project has
no frontend test suite, pre-existing gap); verified via a standalone Node script running
`parseUtc` against the real captured values from the live bug, and via `vite build`
(zero errors) + `oxlint` (pre-existing warning patterns only, no new class introduced).

---

## Sidebar Logo Label Overflow Fix

Reported by the user with a screenshot: the "NETRAKSH" caption under the sidebar's logo
mark showed as "ETRAKSH" — the leading "N" visibly missing.

**Root cause:** `.sidebar-left` (`index.css`) is a fixed 60px column, the leftmost in the
page's grid layout (`x=0`). The label was `text-[9px]` with Tailwind's `tracking-widest`
(extra letter-spacing) in Space Grotesk — a wide geometric display font — with no width
constraint on the `<span>` itself, so it sized to its own content rather than the sidebar's
60px column. At 9 characters plus the extra tracking, the rendered text was wider than the
column, and because this is the leftmost column with nothing further left, the overflow ran
off the left edge of the browser viewport itself and was clipped there — not wrapped, not
shrunk, just cut off at whatever pixel happened to be x=0.

**Fixed:** `frontend/src/components/Sidebar.jsx` — the label now has an explicit
`width: '40px'` (matching the icon rail below it), no extra letter-spacing, a smaller
`fontSize: '6px'`, and `whiteSpace: 'normal'` / `wordBreak: 'break-word'` as a deliberate
safety net: even if a future font swap or text change runs slightly wide again, it wraps to
a second line inside its own box instead of silently overflowing off-screen the way this
bug did.

**Verified live, not just visually:** rebuilt, reloaded, and confirmed via
`find("NETRAKSH")`/accessibility-tree inspection (not just eyeballing a screenshot) that the
rendered text node is the complete, untruncated word — then re-checked at a mobile
viewport width to confirm the fix holds there too, since the original bug was itself a
viewport-edge clipping issue.

---

## Sidebar Widened for Legibility

Follow-up to the clipping fix above — the user reported the logo and "NETRAKSH" label were
now correct but too small to read comfortably at the 60px sidebar width that fix was
squeezed into.

**What changed:** `.app-container`'s grid (`index.css`) widened from `60px 1fr 280px` to
`88px 1fr 280px` — still a compact icon rail, comparable to Linear/Notion's collapsed
sidebars, not a labeled nav. Inside `Sidebar.jsx`: the logo box grew 40px → 52px (mark
26px → 36px), the caption grew 6px → 10px font with its width constraint raised to match
(40px → 68px, still with the same wrap-as-safety-net from the previous fix — not relying on
an exact fit), and the five nav icons grew 20px → 22px in individually-sized 48px boxes
(previously an ambiguous shared container with no explicit per-icon size).

**Verified:** confirmed via `find("NETRAKSH")` that the label text is still the complete
word (not re-broken by the size increase), re-checked at mobile viewport width again since
widening a fixed grid column can shift how much room remains for the rest of the layout,
and grepped the whole frontend for any other place that assumed the old 60px width before
this change — none found.

---

## Sidebar Label: Actually Centered, Not Just Boxed Center

Follow-up to the widening above — the user reported "NETRAKSH" still didn't look centered
under the logo, and asked for it a little bigger.

**Root cause, found by measuring rather than assuming:** the label's Tailwind `text-center`
utility class computed to `text-align: start`, not `center` — confirmed with
`getComputedStyle()`, not guessed from the screenshot. The label's own *box* was correctly
centered within the sidebar (both had the same center-X, measured via
`getBoundingClientRect()`), but the *text glyphs inside that box* were left-aligned within
it, since `text-align` wasn't actually applying — the rendered word (~52px) sat flush left
inside its wider (68px) box, leaving empty space on the right, which reads as the whole
thing being shifted left even though the box itself wasn't.

**Fixed:** `textAlign: 'center'` set as an inline style rather than via the `text-center`
class, which always wins regardless of whatever was overriding the utility class (not
investigated further, since the inline fix is correct either way and this project doesn't
otherwise depend on that specific utility working). Font size bumped 10px → 11px per the
"lil enlarge" request, box width 68px → 72px to keep margin either side.

**Verified with real coordinates, not a screenshot:** measured the text's own true rendered
bounding box (via a `Range` over the span's contents, not the span element's own box) before
and after — center-X went from measurably off-center to within 0.4px of the sidebar's exact
center-X. This is the same class of mistake as the original clipping bug: a box being the
right size or position is not the same claim as its visible content being centered inside
it, and this document doesn't blur the two.

---

## Full Button Audit: Every Interactive Element Checked Live

Prompted by "check in the ui, if every buttons fully functional or not... check everything
properly." Every `onClick`/`<button>`/`<Link>`/`<input>` in the frontend was enumerated
(grepped, not sampled) and exercised live — clicked, watched the real network request,
or explicitly identified as already-verified in an earlier pass. Three new real findings,
all fixed:

**1. Header's Sync Status panel had two hardcoded claims never backed by anything.**
"Last Sync: Just now" — no backend anywhere tracks a real last-sync timestamp
(`SyncStatusResponse.last_sync_at` exists as a schema field but no endpoint ever populates
or returns it) — now honestly shows "Not tracked" instead of a fabricated recency claim.
"Chain Integrity OK" was a static literal regardless of any real state — but
`GET /system/verify-chain` (public, backend/api/system.py) already exists and does a real
check across every stored `EvidencePackage.verified_ok`. Wired the panel to call it when
opened.

**Consequence worth knowing about before a live demo:** this real check now honestly
reports `"N block(s) failed integrity verification. Chain compromised."` in red — not a
bug, exactly the intended behavior — for any event whose `EvidencePackage` doesn't carry a
real, verifiable Ed25519 signature. Checked both databases directly: this local dev
database reports 1157 (accumulated synthetic test events from this entire engagement,
including this session's own demo/test injections); the live Render deployment currently
reports 8 (the demo-seed events from "seed some realistic demo events," which were sent
with a clearly-labeled `"demo-seed-not-a-real-signature"` stub, not a real signature). This
was surfaced, not hidden — flagged directly to the user rather than shipped silently, since
opening this panel during a live demo would show red "Chain Compromised" text. Not
resolved here: whether to re-seed the demo data with real signatures, accept the honest
red state and be ready to explain it, or leave the panel as-is until real signed events
exist. That's a call for the user, not something to decide unilaterally.

**2. Dashboard's [DETECTED]/[UNCERTAIN]/[ABSTAIN] status readout was a `<button>` with no
`onClick` and no `disabled` attribute** — rendered with a pointer cursor and hover states
implying an action that never existed; it's a live status display, not a control. Changed
to `<div role="status">` — identical visual treatment, honestly non-interactive.

**3. "WHY THIS ALERT?" was a `<span>` styled to look like a clickable badge (border,
padding, accent color) with no `onClick` at all.** Rather than just removing the
button-like styling, wired it to something real: a new `explainDecision()` derives the
exact same plain-English breakdown from the already-parsed `decision_reason` data the
Reliability Decision panel displays right next to it — real D/T/S/H values, the real
R-vs-threshold verdict, a real note when the camera was degraded — instead of requiring the
viewer to read four separate numbers out of the Gate 3 grid themselves. Verified live: for
a real posted DEGRADED-camera event, the button correctly toggled a real explanation
string matching the exact D=0.90/T=0.85/S=0.63/H=0.50/R=0.812 shown in Gate 3.

**Confirmed already fully real, not re-tested from scratch:** Sidebar's 5 nav links,
Evidence's search box and Verify button, Alerts' Acknowledge button (all previously
verified end-to-end in earlier passes — see this document's own earlier entries).
**Confirmed still honestly non-functional, as designed:** DemoSidebar's 4 buttons — clicked
one, confirmed via `read_network_requests` a real `405 Method Not Allowed` (the routes
genuinely don't exist), falling through to the local-only "Simulated" UI state exactly as
documented in `docs/LIMITATIONS.md`.

**Tests:** 207/207 passing (no backend changes this pass). Frontend: `vite build` (zero
errors), `oxlint` (one new warning introduced and immediately fixed — an unused parameter
on `explainDecision`; final state has no new warning class), and every fix verified via a
real click + real observed effect (network request, DOM text content, or toggled state
read directly via JS) rather than a screenshot alone.

---

## Demo Events Re-Seeded with Real Ed25519 Signatures

Prompted by "re-seed the demo events with real signatures," after the button audit found
`GET /system/verify-chain` honestly reporting the earlier demo-seed data as failed (it was
sent with a clearly-labeled `"demo-seed-not-a-real-signature"` stub, not a real signature).

**What changed:** `scripts/seed_demo_events.py` (new, committed — the earlier version was a
throwaway scratchpad script) generates a real Ed25519 keypair per demo camera, registers
each public key via the real `PUT /cameras/{id}/public-key`, then builds each event's hash
and signature using the exact same functions the backend verifies against
(`backend/services/verification.py::compute_sha256`, `EvidencePackage.get_signable_fields`
— imported directly, not reimplemented by hand, to guarantee an exact match rather than a
hopefully-matching reimplementation) with correctly chained `sequence_number`/
`previous_hash` per camera. `NETRAKSH_ADMIN_PASSWORD` is read from an environment variable,
never hardcoded — the throwaway version that ran once against the live deployment had the
real password inline; the committed version does not.

**Verified, in the same order as everything else in this project:** dry-run against the
local dev server first (temporarily inserting matching camera/zone rows to mirror the live
deployment, cleaned up after), where every event came back `"verified": true` from the real
ingestion endpoint. Then run for real against the live Render deployment — same result,
all 6 new events verified `true`, and confirmed via `GET /events` that `verified_ok` is
genuinely `True` on each one (not merely returned truthy in the POST response).

**What did NOT get fixed, and why — disclosed, not glossed over:** the OLD 8
fake-signature demo events are still on the live deployment. There is no `DELETE /events`
endpoint (by design — evidence is meant to be append-only) and no direct database access
from this environment, so `GET /system/verify-chain` still reports "8 block(s) failed"
after this change — unchanged from before, because nothing was removed, only added
alongside. Identified the exact 8 `event_id`s (and the 2 `alerts` rows referencing them)
via `GET /events`/`GET /alerts` and handed the user copy-paste SQL to remove them via
Render's own database access, in FK-safe order (`alerts` → `evidence_packages` →
`events`) — that step needs the user's own database credentials, which this session
correctly never had.

**Follow-up, completed:** the user provided the live Postgres's external connection string
directly. Before touching anything, re-queried the exact same 8 `event_id`s directly
against the real database (via `psycopg2`) to confirm the count and FK relationships
matched what the API had already shown (8 events, 8 evidence_packages, 2 alerts) — not
assumed from the earlier read. Ran the three deletes in one transaction, in FK-safe order,
committing only after all three succeeded. Verified immediately after via the real
`GET /system/verify-chain`: `"is_valid": true, "message": "Successfully verified 6 blocks
across all edge hash chains."` — confirmed live in the browser too (the Sync Status panel
now shows this in green), and confirmed the remaining 2 real cross-command alerts and both
camera health cards still render correctly, nothing else was disturbed by the cleanup.

---

## Edge Performance Dashboard — New Feature

Prompted by "what more advanced features... for the SIH" → "Start on the Performance
dashboard." `edge/instrumentation/metrics.py`'s `PipelineMetrics` has measured real
`perf_counter()` per-stage latency, real measured FPS, and real `psutil` CPU/RSS every
frame since early in this project — but it only ever wrote to a local JSON file on the edge
device (`edge/data/metrics_*.json`). Nothing exposed this anywhere; the same shape of gap
Camera Health had before this engagement closed it.

**What changed:**
- `backend/models/orm.py`: new `PipelineMetricsSnapshot` table — one real snapshot per
  edge-device report. Per-stage breakdowns (`frames`/`events`) are stored as `JSON` columns
  rather than exploded field-by-field, since that stage set is owned by
  `PipelineMetrics.FRAME_STAGES`/`EVENT_STAGES` in edge code, not this table.
- `shared/schemas.py`: `PipelineMetricsReport` (ingest) / `PipelineMetricsResponse` (read) —
  the exact shape `PipelineMetrics.summary()` already produces, not reinvented.
- `backend/api/system.py`: `POST /system/metrics` (real ingestion, same MVP no-auth posture
  as `POST /events`/`POST /cameras/{id}/health`), `GET /system/metrics` (latest snapshot per
  distinct edge device — same "one row per known X" shape as `GET /cameras`), and
  `GET /system/metrics/history` (recent snapshots for one device, for a future trend line).
- `backend/api/websocket.py`: new `broadcast_metrics()`, same pattern as
  `broadcast_camera_health`.
- `edge/main.py`: `_report_metrics()` (previously local-JSON-only) now also POSTs the same
  real summary to the backend — best-effort, same failure posture as
  `_report_camera_health()` (never interrupts the frame loop; not routed through the
  offline sync queue, since this is a heartbeat, not evidence).
- `frontend/src/pages/Performance.jsx` (new page, `/performance` route, new sidebar icon):
  fetches `GET /system/metrics` on load, merges live WS `pipeline_metrics` pushes, shows
  real FPS/CPU/RSS tiles, real per-stage latency tables (mean/p95/max, with real sample
  counts), and real Adaptive Compute Gate skip-ratio stats — with an honest empty state
  ("No edge device has reported... yet") rather than ever fabricating a number, matching
  every other page's convention. `frontend/src/hooks/useWebSocket.js` gained a `metrics`
  slice for the new message type.

**Verified live, every state, not just the happy path:** POSTed a real-shaped synthetic
snapshot (the exact structure `PipelineMetrics.summary()` produces) and confirmed
`GET /system/metrics` round-trips it exactly; confirmed the auth-required state (cleared
localStorage, reloaded, got the login form); confirmed the honest empty state (no rows);
confirmed the live WS path specifically — POSTed a second update while the page was open
and watched FPS/CPU/uptime change in the browser with no reload, not just checked the
network log. Test data cleaned up from the local database afterward.

**What did NOT change:** no change to how `PipelineMetrics` itself measures anything —
this is purely a "connect the already-real data to somewhere it can be seen" change, same
category as the Camera Health wiring.

**Tests:** 207/207 passing (no existing test broken by the new table/columns — this is
purely additive; `Base.metadata.create_all()` picks up the new table on next boot with no
migration script needed, since it's a new table, not a new column on an existing one). No
new backend HTTP-level test added (same pre-existing, documented gap as every other
endpoint in this codebase — see `docs/LIMITATIONS.md` §2); verified instead via the live
POST/GET/WS sequence above, this project's established method for exactly this kind of
check. Frontend: `vite build` (zero errors), `oxlint` (two pre-existing warning patterns
only, no new class introduced).

---

## Performance Dashboard Seed Data + a Real Design Flaw Found While Seeding It

Prompted by "seed some realistic synthetic performance data." `scripts/seed_demo_metrics.py`
(new) uses the *real* measured frame-level latency and FPS from
`docs/PERFORMANCE_REPORT.md` (health/detection/event/total stage mean/p95/max,
FPS=21.76) rather than inventing new numbers — the same actual benchmark run this project
already has on record. Per-event stage timings and adaptive-gate skip-ratio are disclosed
as plausible illustrative values, not measurements — that report's own event-level table
says "Not measured in this run," and no adaptive-gate numbers exist anywhere in this
repo's docs either.

**A real bug in `Performance.jsx` itself, found while seeding, not before:** the page
gated *both* the CPU and RSS tiles behind a single shared `psutil_available` flag. But
`docs/PERFORMANCE_REPORT.md`'s own real finding is that the CPU reading from that run
(0.0%) is explicitly "not credible... do not put 0% CPU in the PPT," while the RSS reading
from that *same* run is explicitly credible and quotable. A single shared gate meant that
correctly hiding the uncredible CPU number would have also hidden the real, credible RSS
number for no reason. Fixed: each tile now gates independently on its own field being
non-null, with a sub-label distinguishing "not sampled this run" (a field genuinely absent
from a given report) from "psutil not installed on edge" (the tool itself unavailable) —
two different real reasons a number can be missing, now told apart instead of collapsed
into one message.

**Verified:** re-seeded after the fix and confirmed live — CPU tile correctly shows
"— not sampled this run," RSS tile correctly shows the real "420 MB," alongside the real
FPS and stage-latency numbers, all matching `docs/PERFORMANCE_REPORT.md` exactly. Local
test rows cleaned up from the database both before and after the fix.

**Tests:** 207/207 passing (backend unchanged this pass). `vite build` clean, `oxlint`
clean (same two pre-existing warning patterns as the feature's own introduction, no new
class).

---

## Real Geospatial Map + a Systemic Layout Bug Found Building It

Prompted by "Start on the real geospatial map." The Alerts page's map used to be pure
decoration: a static background image with 3 hardcoded pixel positions named "SECTOR 7" /
"HQ" / "NODE C", tied to nothing real — no camera anywhere in this project had real
coordinates (no `latitude`/`longitude` field existed at all).

**What changed:**
- `backend/models/orm.py`: `Camera` gained `latitude`/`longitude` (`Optional[float]`), added
  to `_migrate_add_missing_columns()` (`backend/database/session.py`) the same way
  `evidence_key_wrapped` was — a real `ALTER TABLE` guard, not a fresh-table-only change,
  verified against the real local dev database's existing camera rows (no crash, correctly
  `null` until set).
- `shared/schemas.py`: `CameraStatusResponse` widened with the same two fields;
  `CameraLocationUpdate` for the new endpoint below.
- `backend/api/cameras.py`: `PUT /cameras/{id}/location` (ADMIN) — real coordinate
  registration. `POST /cameras` (register) also accepts them now.
- `backend/main.py`'s `_seed_demo_data`: the two demo cameras placed near the real,
  publicly-known Attari-Wagah border checkpoint (Punjab) for geographic plausibility —
  disclosed clearly in code comments as NOT real deployed camera positions or an implied
  actual MHA installation, same spirit as every other seed script in this project.
- `frontend/src/components/TacticalMap.jsx` (new): a real Leaflet map (OpenStreetMap
  tiles), plotting every camera with real coordinates, colored by that camera's actual
  `health_state`, with a pulsing ring on any camera currently carrying an unacknowledged
  real alert — not a separately-invented pin. Vanilla Leaflet, not `react-leaflet`: this
  project is on React 19, which `react-leaflet` doesn't yet reliably support.
- `frontend/package.json`: added `leaflet` (real npm dependency, not a CDN script — this is
  a normal Vite app, not a sandboxed Artifact).

**A real Leaflet initialization bug, found live, not assumed:** the map rendered into only
a fraction of its container on first load (a visible black gap below the tiles). Leaflet
reads its container's size once, at construction — the flex-sized panel around it hadn't
finished settling by then. Fixed with a `ResizeObserver` on the container calling
`map.invalidateSize()`, plus one delayed call for the very first paint.

**A much bigger, systemic bug found in the process, affecting far more than the map:**
building this page's 2-column layout (`grid grid-cols-1 lg:grid-cols-2`) revealed that
`.grid`, every `grid-cols-*`, and every responsive breakpoint class (`md:`, `lg:`, `xl:`)
used throughout this frontend do **nothing** — this project has no Tailwind compiler, only
a small hand-written CSS subset (`index.css`), and none of those classes were ever defined
in it. Confirmed via `getComputedStyle` (`gridTemplateColumns` came back `"none"`), not
assumed from a screenshot — the exact same root cause as the earlier `text-center` bug in
`Sidebar.jsx`. Grepped the whole frontend for every other `grid`/`grid-cols-*` usage and
found **6 more**, across `Health.jsx` (the camera-cards grid and each card's own FPS/blur/
exposure/sync 2×2), `Evidence.jsx` (the metadata 2×2), `Dashboard.jsx` (Gate 3's D/T/S/H
4-up and the DETECTED/UNCERTAIN/ABSTAIN 3-up), and `Performance.jsx`'s stat tiles — every
one of them had been silently collapsing to a single column this whole time. Fixed all 6
the same way: real CSS Grid via inline `style`, using `repeat(auto-fill, minmax(...))` in
place of the (non-functional) responsive breakpoint classes — genuine responsive column
count with zero media queries needed at all.

**Verified, every one, not just the map:** live screenshots of Camera Health (cards now
genuinely side-by-side, each card's stat grid genuinely 2×2), Evidence (metadata genuinely
2×2), Dashboard (posted a real event and confirmed Gate 3's D/T/S/H render as 4 real
columns, and the status-pill row as 3 real columns), and Performance (4 real stat-tile
columns) — before-and-after, not a single one taken on faith. Real coordinates set on the
local dev database's actual existing cameras (`edge-001`, `CAM-07`) via the new endpoint,
confirmed the map plots them at the right position with a working popup showing real
name/location/health, cleaned up afterward.

**What did NOT change:** no other CSS classes were audited or touched — only the 7 total
`grid`-family usages found by an exhaustive grep. Whether the same "utility class name
looks like Tailwind but isn't backed by anything" pattern affects other class families
(`text-*` alignment/size variants beyond the one `text-center` case already found, spacing
utilities beyond `gap-*` which was confirmed real, etc.) was not investigated — flagged in
`docs/LIMITATIONS.md`, not silently assumed fine.

**Tests:** 207/207 passing (backend additive only — new columns via the established
migration guard, no existing behavior changed). `vite build` clean, `oxlint` clean (same
pre-existing warning patterns throughout, no new class introduced by any of the 7 fixes).

---

## Role-Differentiated UI

Prompted by "Start on the role-differentiated UI." RBAC (ADMIN/OPERATOR/AUDITOR) has been
fully real on the backend since early in this project — every write endpoint already
enforces it server-side — but the frontend showed every logged-in viewer an identical
screen regardless of role, never displayed who was signed in, and had no logout anywhere.
The real `/auth/token` response has always included `username` (`backend/api/auth.py`,
`TokenResponse.username`) — the frontend was silently discarding it.

**What changed:**
- `frontend/src/services/auth.js`: now stores `username` (was discarded), and `login()`/
  `logout()` dispatch a new `AUTH_CHANGE_EVENT` so any mounted component reacts live —
  plain `localStorage` reads aren't reactive on their own.
- `frontend/src/hooks/useAuth.js` (new): subscribes to that event plus the browser's own
  `storage` event (cross-tab sync), giving any component a live `{ isAuthenticated, role,
  username }`.
- `Header.jsx`: the user icon was purely decorative (no click handler, no session info,
  nowhere to sign out in the entire app). Now a real account panel — shows the actual
  signed-in username and role (color-coded), or `LoginPrompt` when signed out, with a
  working Sign Out button. The icon's border color itself reflects the real role at a
  glance (red=ADMIN, green=OPERATOR, amber=AUDITOR).
- `Alerts.jsx`: the Acknowledge button now only renders for ADMIN/OPERATOR — AUDITOR sees
  a real "View only" indicator instead of a button that would always 403. Confirmed the
  backend still rejects the real request directly (not just hidden in the UI): `POST
  /alerts/{id}/acknowledge` as `auditor` → real `403`, exact message
  `"Role 'AUDITOR' is not permitted for this action. Required: ['ADMIN', 'OPERATOR']"`.
- `frontend/src/pages/CameraManagement.jsx` (new), `/camera-management` route, new
  ADMIN-only sidebar icon: the first genuinely role-exclusive page in this app. Exposes
  `PUT /cameras/{id}/location` and `POST /cameras` — both real, ADMIN-gated endpoints that
  existed since the geospatial map work but were only ever reachable via a script or curl.
  Lists every camera with inline coordinate editing and a camera-registration form. The
  sidebar icon itself only renders when `role === 'ADMIN'`; the page's own content still
  checks the real role too (not just the nav-icon visibility) and shows an honest "ADMIN
  only" message otherwise — confirmed the real backend still rejects a non-admin's request
  directly: `PUT /cameras/{id}/location` as `auditor` → real `403`.

**Verified live, every role, not just one:** cleared all session state, logged in as
`auditor` (real seeded account, `bootstrap_users` — same for `operator`), confirmed the
account panel showed the real username/role, confirmed the Camera Management sidebar icon
was absent, confirmed Alerts showed "View only" on unacknowledged alerts. Logged in as
`admin`, confirmed the Camera Management icon appeared, opened it, set a real camera's
coordinates through the real UI form, confirmed the change round-tripped to the real
database and the Alerts page's map picked it up immediately. Logged out through the real
Sign Out button and confirmed the header reverted to "Not signed in" and the Camera
Management link disappeared instantly — no page reload, `AUTH_CHANGE_EVENT` doing its job.

**What did NOT change:** no backend RBAC logic — every permission boundary described above
was already real and enforced before this pass; this is purely a "show it, don't hide it"
frontend change; the client-side role checks are conveniences for the UI, never the actual
enforcement.

**Tests:** 207/207 passing (no backend changes). `vite build` clean, `oxlint` clean (same
pre-existing warning patterns, no new class introduced).

---

## UI Bug Sweep + Cross-Camera Corroboration (§12B/§13) — First Real Implementation

**Context:** a full pass across every dashboard page looking for the same class of bug this
whole project has repeatedly found and fixed all session — a hardcoded/fabricated value shown
regardless of real state — plus building the one piece of the architecture poster that grepping
the entire repo confirmed did not exist anywhere: cross-camera corroboration and the temporal
consistency formula `Tc = e^(-|Δt-t_expected|/σ)`.

**UI bugs found and fixed (all frontend-only, Python side unaffected):**
1. `VideoFeed.jsx` drew a hardcoded "PERSON #184 | 91% CONF" bounding box on every page load,
   before any real event ever happened — the only guard was `!isConnected && !eventData`, and
   Dashboard always passes `isConnected={true}`. Now the box (and its label) render only when a
   real `eventData` exists; idle state shows an honest "Monitoring — no active event".
2. `.app-container`'s grid header row was a hard `60px 1fr`. Confirmed via the rendered `<h1>`'s
   own bounding box (`top: -6.4px` — genuinely above the header, not a screenshot artifact) that
   on any viewport narrow enough for the subtitle to wrap past one line, the header's real
   content height exceeded 60px and the title clipped. Changed to `minmax(60px, auto) 1fr`.
3. `Header.jsx` polled `GET /sync/status` and `GET /system/status` every 5s unconditionally, even
   signed out — both require `require_any_role`, so every anonymous visit 401'd forever. Both
   polls now gated on `isAuthenticated`.
4. `Evidence.jsx`'s metadata card showed `selectedEvent?.event_type || 'Human'` for "DETECTION
   TYPE" (wrong field — `event_type` is the rule that fired, not what was detected — plus a
   hardcoded fallback) and a hardcoded `"edge-001 (Active)"` for "EDGE NODE" regardless of which
   real device produced the event. Fixed to use the real `detection_class` field, and to show the
   real `edge_device_id` (see below — it was always stored on ingest, just never returned to the
   frontend).
5. `Architecture.jsx` — the worst offender — stated several things as fact that directly
   contradict the real running system: "TensorRT Optimized" (never true; plain CPU YOLOv8n per
   `docs/PERFORMANCE_REPORT.md`'s own measured run), a fabricated fixed "FPS 30.0 / RESOLUTION 4K
   UHD", reliability-gate bands of "DETECTED ≥85% / UNCERTAIN 50-84% / ABSTAIN <50%" (not the real
   gate at all — the real engine is `R = 0.40D+0.20T+0.20S+0.20H` banded at 0.75, and ABSTAIN is
   Gate 1's camera-health hard override, not a low-R band), a hardcoded SHA-256 value that is
   specifically the well-known hash of the *empty string* (looks like a real captured value but
   isn't), and "Hyperledger Fabric consensus network" stated as settled fact when
   `backend/services/blockchain.py`'s own honest runtime label is MOCK mode. All corrected to say
   what the running system actually says about itself.

**Cross-camera corroboration — `backend/services/cross_camera.py` (new):** the poster's §12B/§13
box ("cross-camera detection is checked against neighbouring cameras using topology, timestamps
and ETA") and its `Tc` formula had zero implementation anywhere before this — confirmed by
grepping the whole repo for "corrobora", "topology", "ETA", "Tc =" and finding nothing outside
poster/doc text. Honest scope, in full in that module's docstring:
- No hand-entered topology graph (the poster's own "80m / ETA 8-30s" is illustrative demo data,
  not something honestly assertable about hardware never deployed). Instead, real distance is
  computed via haversine from each camera's real, admin-entered `latitude`/`longitude`
  (`backend/models/orm.py`'s `Camera` — already collected for the geospatial map). Expected
  travel time is a real range derived from that real distance and a disclosed walking-speed
  heuristic (`ASSUMED_MIN_SPEED_MPS`/`ASSUMED_MAX_SPEED_MPS` = 0.8–2.2 m/s) — same category as
  this project's other hand-picked-but-justified constants, not a fabricated measurement.
- **Not person re-identification.** No face/appearance embedding exists anywhere in this
  codebase. "Corroboration" means temporal+spatial *plausibility* only: a same-`detection_class`
  sighting at a geographically nearby camera within a physically-plausible travel time. Stated
  everywhere this score is surfaced (docs, API field names, UI labels — all say "corroboration",
  never "identity").
- **Never retroactively rewrites an already-signed event.** The edge that made the original
  DETECTED/UNCERTAIN/ABSTAIN decision has no visibility into other cameras and signs its evidence
  package before any cross-camera information could exist; mutating a signed event afterward
  would break the tamper-evident chain-of-custody the rest of the system depends on. Instead, the
  backend computes and stores corroboration as separate, additional columns
  (`corroboration_score`, `corroborated_by_event_id`, `corroboration_distance_m`,
  `corroboration_delta_t_s`) on the `Event` row, immediately after ingest
  (`backend/api/events.py::ingest_event`, non-fatal on failure — same posture as
  escalation/blockchain). Symmetric: the matched event is back-filled too, so either event's
  record shows the corroboration.
- Deliberately conservative: `MAX_CORROBORATION_DISTANCE_M` (2km) and `MIN_TC_TO_RECORD` (0.15)
  mean most events will have no corroboration at all — and that absence is shown honestly on the
  Evidence page ("No corroborating sighting found") rather than a fabricated score.

New DB columns via the existing migration-guard pattern (`backend/database/session.py`, same
`ALTER TABLE ... ADD COLUMN` approach as `cameras.evidence_key_wrapped`/`latitude`/`longitude`) —
safe on the real, already-populated `netraksh.db`. `EventResponse` (`shared/schemas.py`) gained
the four corroboration fields plus `edge_device_id` (a field that was always stored on ingest but
never exposed — the direct cause of Evidence.jsx bug #4 above). Surfaced on the Evidence page's
metadata card.

**Tests:** `tests/unit/test_cross_camera.py` (new, 20 tests) — pure-formula tests (haversine
correctness against an independently-known real distance, expected-travel-time bounds, `Tc`
formula behavior including the zero-width-range/division-by-~0 guard) and DB-backed matching
tests (an in-memory SQLite with real `Camera`/`Event` rows: finds a genuinely plausible match,
picks the best of several candidates, honestly returns `None` for missing coordinates, an
implausible real distance, a class mismatch, or implausible timing — never fabricates a match).
`tests/unit/test_db_migration.py` gained 3 tests for the new events-table columns (adds them,
preserves existing rows, idempotent). Full suite: 277/277 (254 + 23 new).

---

## Real Dataset Sourced — MOT16, and the First Real Calibration Fit This Project Has Ever Had

**Why:** every calibration attempt all session (`scripts/fit_reliability_weights.py`,
`scripts/fit_detection_thresholds.py`) hit the same real wall — this project's only real footage
(`demo/videos/vtest.avi`) has zero real false positives once reviewed, so there was never a real
negative example anywhere to fit a threshold against. Sourcing an external real dataset with real
ground truth was the direct fix, not more engineering on the same single video.

**Dataset chosen:** MOT16 (Milan et al., "MOT16: A Benchmark for Multi-Object Tracking",
arXiv:1603.00831, https://motchallenge.net), CC BY-NC-SA 3.0, non-commercial research use — real
CCTV/street footage with real, human-annotated pedestrian ground truth (`gt/gt.txt`). Considered
and rejected smaller alternatives first (UCSD Anomaly Dataset, 706MB, low-res grayscale, no
ground-truth boxes suitable for FP/TP labeling; OpenCV sample clips, small but daytime-only, no
diversity gain) — user chose MOT16 explicitly after being shown the size/license tradeoffs of
each. Downloaded the real 1.95GB archive, extracted only two real train sequences with ground
truth (MOT16-02, MOT16-04 — the `test/` split has no `gt.txt`, by design of the benchmark). Raw
dataset and per-candidate snapshot crops are gitignored, same as this project's own
`calibration_data_*/snapshots/`; only derived `manifest.json` files (numeric data, no image
bytes) are committed.

**New: `scripts/collect_mot16_ground_truth_calibration.py`.** Runs the real YOLOv8n detector
(same model this whole project uses) at a low confidence floor (0.05) against real MOT16 frames,
and labels every raw candidate against real ground truth by IoU: ≥0.5 with a real GT pedestrian
box → real detection (label=1); <0.1 with every real GT box → real, GT-verified false positive
(label=0); anything between is genuinely ambiguous and excluded from the manifest, never guessed.
Real, measured results:

| Sequence | Frames (stride) | Candidates | Real detections | Real false positives |
|---|---|---|---|---|
| MOT16-04 (marketplace) | 1050 (10) | 3834 | 3122 | **712** |
| MOT16-02 (street) | 600 (5) | 3268 | 1851 | **1417** |

**New: `scripts/fit_detection_thresholds_mot16.py`.** Fed both manifests into
`CalibrationModule.fit()` (the same real module every prior attempt this session correctly
refused to fit on single-class data). Both now produce a real, non-degenerate isotonic fit — the
first time all session this project has had genuine negative examples to calibrate against:
MOT16-04 → threshold **0.410**; MOT16-02 → threshold **0.100**.

**The honest headline finding is that these two real numbers disagree.** Rather than pick one and
call it "the" calibrated threshold, this is reported as-is: a confidence threshold fitted on one
real camera/crowd-density does not obviously transfer to a different one. Neither value is applied
to `edge/detection/calibration.py`'s runtime `THRESHOLD_*` defaults — doing so would mean silently
resolving a real disagreement in favor of whichever number looked more convincing, on a camera
neither MOT16 sequence was even filmed on. This is the same discipline this project has applied to
every other calibration attempt: report the real result, including when the real result is
"these two real answers don't agree yet" — see `docs/LIMITATIONS.md` for the full account.

**Tests:** `tests/unit/test_mot16_ground_truth_calibration.py` (new, 9 tests) — real IoU
computation (identical/disjoint/known-fraction/symmetric/degenerate-zero-area boxes) and real
MOT16 `gt.txt` parsing (filters to the real pedestrian class code, honors the devkit's
conf=0-means-ignore convention, handles an empty file). Full suite: 286/286 (277 + 9 new).

---

## Cross-Camera Corroboration Wired Into Escalation

**Context:** cross-camera corroboration (above) was deliberately left display-only when first
built, since wiring it into real alerting behavior is a product decision, not an engineering one.
User explicitly asked for it to be wired into `backend/services/escalation.py` — done here.

**The change:** a MEDIUM-severity event with strong real cross-camera corroboration
(`event.corroboration_score >= CORROBORATION_BOOST_MIN_TC`, 0.6 — deliberately much stricter than
`cross_camera.py`'s own `MIN_TC_TO_RECORD` of 0.15, since this threshold now gates a real change
in alerting behavior, not just a display annotation) is now also treated as escalation-eligible,
alongside the existing HIGH-severity condition. Scoped narrowly and disclosed on purpose:
- **Only MEDIUM is boosted, never LOW** — `CORROBORATION_BOOST_SEVERITY = Severity.MEDIUM.value`,
  hardcoded, not a sliding scale.
- **The original, already-signed `Event.severity` field is never mutated** — same principle as
  cross-camera corroboration itself never rewriting a signed event. The boost only affects this
  function's local escalation-eligibility check for this one call.
- **Every alert created via the boost is transparently marked.** New `Alert.escalated_via_corroboration`
  column (added via the existing migration-guard pattern), `false` for every HIGH-severity alert
  (which needed no boost — verified by a dedicated test), `true` only when the boost is why the
  alert exists at all. Exposed through `AlertResponse`, the WebSocket broadcast payload, and shown
  on the Alerts page ("Escalated via cross-camera corroboration...") — never a silent behavior
  change.
- **Condition 2 (crosses a jurisdiction boundary, for blockchain submission) is unaffected** — the
  boost only ever widens which events pass condition 1; a boosted alert still needs a real boundary
  zone to reach the blockchain, exactly like a HIGH-severity one.

**Tests:** `tests/unit/test_escalation.py` (new, first-ever for this module, 12 tests) — regression
coverage (HIGH escalates exactly as before, with or without a corroboration score; MEDIUM without
strong-enough corroboration still doesn't escalate at all) and new coverage (MEDIUM + strong
corroboration escalates and is marked; exact-threshold boundary; just-below-threshold does not
escalate; LOW is never boosted regardless of corroboration strength; a boosted alert can still
reach the blockchain via a real boundary zone; idempotency). Full suite: 298/298 (286 + 12 new).

---

## Real Production Incident: Postgres Deploy Crash From a SQLite-Only-Tested Migration

**What happened:** the `escalated_via_corroboration` migration above shipped as
`ALTER TABLE alerts ADD COLUMN escalated_via_corroboration BOOLEAN DEFAULT 0` — passed the full
local test suite (298/298) and was pushed. The live Render deployment (Postgres, per
`render.yaml`) crashed on startup:

```
sqlalchemy.exc.ProgrammingError: (psycopg2.errors.DatatypeMismatch) column
"escalated_via_corroboration" is of type boolean but default expression is of type integer
ERROR:    Application startup failed. Exiting.
==> Exited with status 3
```

**Root cause, stated plainly:** SQLite has no real `BOOLEAN` type — it stores `0`/`1` as plain
`INTEGER` and accepts `DEFAULT 0` on a column declared `BOOLEAN` without complaint. Postgres
enforces the real type and correctly rejects an integer literal as a boolean column's default.
Every local test in this project's suite runs against SQLite (`sqlite:///:memory:` or a temp
file) — there is no Postgres available in this dev environment to test against directly (the same
class of honest gap as the WSL2/Docker unavailability documented for the blockchain mock). So
298/298 passing locally was real and honest, and still shipped a real production-crashing bug —
this project's test suite structurally cannot catch a SQLite/Postgres divergence, and this is the
first time that gap actually mattered.

**Found via:** the user asked to verify the live Render deployment reflected the latest push.
Polling the live site's served JS bundle hash for ~15 minutes showed zero change — long enough to
rule out "just a slow build" — then the user pasted the real Render deploy log, which contained
the exact stack trace above.

**Fix:** `DEFAULT FALSE` (a real boolean literal, valid in both SQLite and Postgres) instead of
`DEFAULT 0`. Since the failed deploy's `ALTER TABLE` ran inside a transaction
(`engine.begin()`) that rolled back on the exception, the live Postgres database was never left in
a partially-migrated state — the next deploy runs the (now-fixed) migration cleanly from scratch.

**What was added so this doesn't recur:**
- `tests/unit/test_db_migration.py::TestMigrationAddsEscalationCorroborationColumn` (3 tests) — the
  same SQLite-based coverage every other migration in this guard already had (this column simply
  didn't have any before the incident).
- `tests/unit/test_db_migration.py::TestMigrationSqlIsPostgresCompatible` (1 test) — a direct,
  cheap regression guard: greps `backend/database/session.py`'s own source for any
  `ALTER TABLE ... BOOLEAN ...` migration using an integer `DEFAULT 0`/`DEFAULT 1` literal instead
  of `TRUE`/`FALSE`. Verified this test actually fails against the original buggy line (reverted
  it, watched the test fail with a clear message, restored the fix) before trusting it — not just
  assumed. This does not replace real Postgres testing (still not available in this dev
  environment) but catches this exact real bug pattern, and any future BOOLEAN migration written
  the same way, going forward.

Full suite: 302/302 (298 + 4 new).

---

## Demo Scenario Control Panel — Fixed to Actually Do Something

**Found via:** user reported "Demo Scenario Control not working". Confirmed real: clicking any of
the 4 buttons (Normal Ops/Dense Fog/Sensor Failure/Offline State) toggled only that button's own
highlight — `activeSim` was local `useState` inside `DemoSidebar.jsx` alone, read by nothing else
in the frontend. Each click also called `/demo/inject-condition`, `/demo/trigger-camera-failure`,
`/demo/simulate-offline` — none of which exist anywhere in the backend (no `backend/api/demo.py`
or equivalent router; grepped to confirm) — so every click also silently 401'd/404'd for zero
benefit. The panel visually worked (no JS error, no crash) while being functionally inert, which
is exactly why it looked fine in earlier passes but genuinely wasn't.

**Fix:** `frontend/src/hooks/useDemoScenario.jsx` (new) — a small React Context making the
selected scenario real, shared, app-level state instead of one component's private `useState`.
`App.jsx` wraps the whole router in it. Removed the dead `/demo/*` calls entirely rather than
leaving them silently failing.

Wired to real, visible effects, each clearly labeled "SIMULATED" so it can never be mistaken for a
real edge-reported condition:
- **Dense Fog** — `VideoFeed.jsx` shows a fog-tint overlay + "SIMULATED: FOG_RAIN — IR fallback
  engaged" badge.
- **Sensor Failure** — a red-bordered overlay + "SIMULATED: SENSOR FAILURE" badge.
- **Offline State** — `VideoFeed.jsx` switches to its real disconnected view (previously only
  reachable via a real disconnected WebSocket), and `Header.jsx`'s "EDGE: ONLINE" badge — itself a
  real, separate bug (hardcoded regardless of any real state, same class as several other
  hardcoded-badge bugs found this session) — now honestly flips to "EDGE: OFFLINE" while this
  scenario is selected.
- **Normal Ops** — resets all of the above.

Verified interactively (not just built and assumed): clicked each of the 4 buttons and confirmed
the correct badge/overlay text appears via the rendered DOM; confirmed the selection survives real
in-app navigation (sidebar `<Link>`, not a full page reload) by selecting Offline State on the
Dashboard, navigating to Camera Health via the sidebar, and confirming "EDGE: OFFLINE" was still
shown there — proving the state is genuinely app-level now, not page-local. Frontend-only change;
Python suite unaffected (302/302).

---

## Tiered Evidence Capture by Condition Quality — a Real Gap Found and Fixed

**Context:** user asked, pointedly, whether this whole session's fixes went any deeper than
surface-level UI polish, and specifically described an expected behavior: worse condition should
still capture *something* locally, not nothing. Audited `edge/main.py`'s FAILED-camera-health
(ABSTAIN, "very poor condition") path directly rather than assuming — confirmed a real gap:
`self._emit_event(..., frame=None, # Don't waste disk on failed camera snapshots)`, called
unconditionally on **every single frame** while the camera stays FAILED. The metadata heartbeat
was real and already synced (used by the Camera Health page), but the actual visual evidence was
never captured at all — if the camera health monitor's own frozen/blur/exposure detection had a
false trigger, there was nothing to review afterward.

**Fix:** `shared/constants.py`'s new `ABSTAIN_SNAPSHOT_INTERVAL_SECONDS` (30s) and
`edge/main.py`'s new `should_capture_abstain_snapshot()` (a small pure function, deliberately
factored out so it's testable without instantiating the full `EdgePipeline` — real YOLO model
load and all). The per-frame ABSTAIN heartbeat itself is unchanged (real, useful telemetry as-is);
a real encrypted snapshot is now captured periodically during a sustained failure instead of
never, without flooding local disk with one encrypted JPEG per frame.

**Scope, stated honestly:** the other two tiers already behaved as expected without changes —
UNCERTAIN (R < 0.75, "a little better") and DETECTED (R ≥ 0.75, "good condition") both already
save full metadata + an encrypted snapshot and go through the complete pipeline; only the FAILED/
ABSTAIN tier had zero visual evidence. This is the specific, real interpretation of "tiered by
condition quality" that closes an actual gap without touching the Camera Health page's existing,
working, tested telemetry.

**Tests:** `tests/unit/test_abstain_snapshot_capture.py` (new, 6 tests) — boundary conditions on
the throttle (captures immediately on the first FAILED frame of a run, not again immediately
after, not just before the interval elapses, captures exactly at and well after the boundary) plus
a guard against the constant ever silently regressing to 0/negative. Full suite: 308/308 (302 + 6
new).

**Also audited and confirmed real** (with file references, since "have you actually implemented
this" deserves evidence, not reassurance):
- SHA-256 hashing, Ed25519 signing, AES-256-GCM encryption, hash chain: all real, all in
  `edge/evidence/packager.py` (`compute_sha256`, `EdgeKeyManager.sign`, `EvidenceEncryptor`,
  `EvidenceChainStore.append`), exercised by `tests/unit/test_evidence.py`.
- Cross-camera corroboration: real, `backend/services/cross_camera.py` (see its own changelog
  entry above).
- Adaptive Compute Gate, Track Continuity Guard, Night-Motion Fallback: all real, all
  instantiated and wired into `edge/main.py`'s real per-frame loop (`self.adaptive_gate`,
  `self.continuity_guard`, `self.night_motion_fallback`) — not merely defined and unused.
- Event Verifier state machine (`edge/temporal/event_verifier.py`): OBSERVED → CANDIDATE →
  VERIFIED → ALERTED is real and exercised (`EventVerifier.observe()`, real confirmation-count
  logic, real cooldown/expiry). **ACKNOWLEDGED is real** (`POST /alerts/{id}/acknowledge`,
  `backend/api/alerts.py`) but **CLOSED is not** — `EventState.CLOSED` exists as an enum value
  with a docstring claiming it's "set later by command-center operator action," but grepping the
  entire codebase confirms nothing anywhere actually sets it. This is a real, open gap, disclosed
  here rather than left to look complete — see `docs/LIMITATIONS.md`.
- **Dashboard UI visibility of the above is uneven, disclosed here directly**: the Adaptive
  Compute Gate's real state (ACTIVE/IDLE, skip ratio) IS shown on the Performance page
  (`frontend/src/pages/Performance.jsx`, from real `PipelineMetrics` data). The Event
  Verifier's OBSERVED/CANDIDATE/VERIFIED progression, Track Continuity Guard re-associations, and
  Night-Motion Fallback firings are real and working on the edge but have **no dashboard
  visualization at all** — a real engine can be entirely real and still invisible to someone only
  looking at the dashboard, which is a fair thing to flag as looking unfinished even where the
  underlying mechanism isn't.

---

## The Real Root Cause: `.absolute`/`.relative` (and ~100 More) Were Never Defined

**Found via:** user reported the Sync Status dropdown rendering overlapping the header instead of
appearing below it, with a screenshot. That specific bug traced to the header's own dropdown
panels using a hardcoded `top-[60px]` that assumed the header row is always exactly 60px tall (it
isn't — see the earlier "Sidebar Logo Label Overflow Fix" / grid-row entries). Fixing that
surfaced something far bigger: `getComputedStyle()` on the panel showed `position: static`, not
`absolute`, even though its `className` literally contained `absolute`. **`.absolute` was never
defined anywhere in `index.css`.** Neither was `.relative`.

**Scope, confirmed by auditing every `className` string used anywhere in the app against what's
actually defined in `index.css`, not guessed:** over 100 classes were in real, active use —
`flex-grow`, `flex-1`, `flex-shrink-0`, `overflow-hidden`, `overflow-y-auto`, every `top-*`/
`left-*`/`right-*`/`bottom-*` offset, every `mt-*`/`mb-*`/`pt-*`/`pb-*`/`px-*`/`py-*` spacing
value, `z-10`/`z-20`/`z-50`, `text-center`, `uppercase`, `truncate`, `shadow-lg`, several
`hover:*`/`disabled:*`/`last:*` pseudo-class variants, and more — with **no matching CSS rule
anywhere**, silently doing nothing. This is the exact same class of bug `docs/LIMITATIONS.md`
already documented for `.grid`/`.grid-cols-N`/`text-center` (found while building the geospatial
map, months before this session) — but that entry explicitly said "not investigated: whether other
class families... have the same problem." They did, far more extensively than anyone had checked.

**Why this looked "fine" for so long:** most of these classes' absence was invisible by pure
coincidence — an un-absolutely-positioned badge still often landed near the right place because it
was early in normal document flow anyway; a missing `flex-grow` still often looked plausible
because a sibling element's own real height propagated close enough. The coincidence only visibly
broke down in specific cases — exactly why a header 60px assumption (real, specific, checkable) is
what finally surfaced it, and exactly why `demo/videos/vtest.avi`-style manual visual review kept
missing it in every earlier pass this session, including several of this session's own.
`getComputedStyle()` caught it in one call; eyeballing screenshots never did.

**Fix:** `frontend/src/index.css` gained a real, comprehensive utility layer for every non-bracket
class actually used in the app, matching the exact Tailwind semantics the JSX was clearly written
against — the same 0.25rem-per-unit spacing scale this file's own pre-existing `.gap-*` classes
already used, not invented. Separately, every bracket/arbitrary-value class that a flat rule can't
cover (`h-[calc(100%-80px)]`, `flex-[3]`, `min-h-[400px]`, `w-[300px]`, `w-[30%]`, `top-[20%]`,
etc. — 12 total, across `Dashboard.jsx`, `Evidence.jsx`, `Alerts.jsx`, `Architecture.jsx`) was
converted to a real inline `style={{...}}`, the same pattern already established for the earlier
`grid`/`grid-cols-N` fix.

**One real regression this surfaced and fixed in the same pass:** once `.absolute` started
actually working, `VideoFeed`'s container — previously kept a real ~400px tall only by badges
accidentally contributing real document-flow height while broken — collapsed to **1.6px**
(confirmed via `getComputedStyle`, not guessed) the moment those badges correctly left the flow,
because `min-h-[400px]` had *also* never been real. Fixed as part of the same inline-style
conversion pass above, not a separate follow-up.

**Verified, not assumed:** `getComputedStyle()` before/after on both the fixed dropdown panel and
the `VideoFeed` container; a full visual sweep of all 7 dashboard pages after rebuilding, looking
specifically for anything now mispositioned or collapsed by the newly-real CSS rather than only
confirming the one reported bug. Full suite: 308/308 (Python-side unaffected — this is entirely a
frontend CSS/JSX change).

**Honestly still open:** a smaller number of purely cosmetic bracket-value classes remain
unconverted — mostly `text-[10px]` (renders at the browser's default font-size instead of 10px)
and several `hover:bg-[rgba(...)]` tint states (renders with no hover-color change at all). None of
these affect layout or functionality, only visual polish, which is why they were deliberately
deprioritized behind the layout-breaking ones above rather than left unmentioned — see
`docs/LIMITATIONS.md`.

---

## Vehicle Classification and Wrong-Direction Detection (SIH PS 26187 gaps)

**Context:** a direct audit against the official SIH problem statement text (26187 — "AI-Based
Intelligent Video Analytics Platform for Border Surveillance") found two literal, real gaps: the
PS asks for "vehicle detection **and classification**", but every YOLO vehicle class (car,
motorcycle, bus, truck) collapsed into one generic `DetectionClass.VEHICLE` everywhere; and
`EventType.WRONG_DIRECTION` — a real enum value, directly relevant to the PS's "suspicious activity
detection" — existed with **zero real producer** anywhere in the codebase, referenced only by its
own definition and a literal string in `scripts/seed_demo_events.py`'s mock data.

**1. Vehicle classification.** New `shared.constants.VehicleSubtype` (CAR/MOTORCYCLE/BUS/TRUCK) and
a parallel `_YOLO_VEHICLE_SUBTYPE_MAP` in `edge/detection/detector.py`, alongside the existing
`_YOLO_CLASS_MAP` — additive, not a replacement: every class id with a real subtype also still maps
to `DetectionClass.VEHICLE` in the original map (tested directly), so every existing piece of
gating logic keyed on `detection_class == VEHICLE` (`ANPRModule`, cross-camera corroboration class
matching, etc.) is completely unaffected. Threaded through the real pipeline end to end:
`TrackData` → `EvidencePackager.package()` → `EvidencePackage` (a new optional field, deliberately
excluded from `get_signable_fields()` — same treatment as `plate_text`/`face_bbox`, doesn't touch
the tamper-evident hash) → `POST /events` ingest → `Event` ORM column (new migration, same
guard pattern as every other column added this session) → `EventResponse` → the Evidence page's
metadata card (`Evidence.jsx`, e.g. "VEHICLE (BUS)" instead of just "VEHICLE").

**2. Wrong-direction detection.** New `ZoneSchema.restricted_direction` (optional — `None` for
every zone that existed before this, so old zone configs behave identically) lets an admin mark one
specific direction on a boundary-line zone (`LineCrossingModule`, e.g. a one-way checkpoint road) as
wrong-way. A crossing in that direction now fires `EventType.WRONG_DIRECTION` instead of an
ordinary `LINE_CROSSING`. `edge/main.py::determine_severity()` gained a dedicated `WRONG_DIRECTION`
→ HIGH case (checked before the generic `LINE_CROSSING` → MEDIUM case, so it doesn't silently fall
through) — a vehicle going the wrong way at a border checkpoint is a specific, real security
concern, not just "a crossing happened."

**A real bug found and fixed by this feature's own tests, not shipped silently:** the first version
of the wrong-direction comparison used `str(direction) == str(line.restricted_direction)` — but
`direction` is a real `(str, Enum)` member, and `str()` on an Enum member returns
`"LineCrossingDirection.A_TO_B"`, not the bare `"A_TO_B"` value `ZoneSchema.restricted_direction`
actually holds (`Config.use_enum_values=True` stores the bare string). The two never matched, so
`WRONG_DIRECTION` would never have fired despite everything else being wired correctly. Caught
because two of the five new tests failed immediately on the first run — fixed to `direction.value
== line.restricted_direction` and re-verified before trusting it.

**Tests:** `tests/unit/test_vehicle_classification.py` (new, 9 tests — the YOLO class-id map's own
internal consistency, `TrackData` round-trip, and `EvidencePackager.package()` carrying the real
value through for a vehicle track, `None` for a person track, `None` when `track` itself is
`None`). `tests/unit/test_line_crossing.py` gained `TestWrongDirection` (5 tests — the regression
that an unconfigured zone still always reports plain `LINE_CROSSING`, the restricted direction
firing `WRONG_DIRECTION`, the *other* direction on the same zone still reporting an ordinary
crossing, the restriction working with either direction value, and the event dict's shape staying
otherwise unchanged). `tests/unit/test_determine_severity.py` (new, first-ever coverage for this
function, 7 tests). `tests/unit/test_db_migration.py` gained 3 tests for the new
`vehicle_subtype` column. Full suite: 331/331 (308 + 23 new).

---

## Real Facial Recognition and External C2 Integration (SIH PS 26187 gaps #3/#4)

**Context:** continuing the direct SIH PS 26187 audit — two more literal gaps, both substantial.
Every prior mention of face recognition in this codebase disclosed it as NOT implemented
(`FaceDetectionModule`'s own docstring: "MVP is detection only. Recognition (ArcFace) is
advanced/stretch."). And "support integration with existing command and control systems" had zero
real code anywhere — this dashboard *is* a command center, but nothing let a genuinely external
one receive anything from it.

### 1. Real watchlist facial recognition

**Dependency change, verified before committing to it, not assumed:** swapped
`opencv-python-headless` for `opencv-contrib-python-headless` — the plain package never ships
`cv2.face` at any version; confirmed the contrib variant installs cleanly on this project's Python
3.14 environment and provides `cv2.face.LBPHFaceRecognizer`, then ran the full existing suite
(331/331 unchanged) to confirm the major version bump (4.14 → 5.0) broke nothing else already
depending on `cv2`.

**New `edge/detection/face_recognition.py`** wraps `cv2.face.LBPHFaceRecognizer` — OpenCV's
classical, CPU-friendly recognizer (Local Binary Patterns Histograms), matching this project's
stated posture throughout (no heavy deep-learning dependency, e.g. `dlib`/`face_recognition`,
which has no reliable prebuilt wheel for this project's Python 3.14 environment — a real,
practical risk avoided, not just a preference). **Honest scope, stated in the module's own
docstring and repeated here because it matters**: NOT a production-grade FRS; real, meaningfully
lower accuracy than modern embedding-based recognizers, especially across lighting/pose/expression;
**no liveness detection** — a printed photo matches exactly like the real person; not appropriate
for large-scale (hundreds+) 1:N identification. Every match is a real LBPH output against real
enrolled photos — never fabricated — but a match is a lead for human review, never a confirmed
identification on its own.

**New backend `WatchlistPerson`/`WatchlistFaceImage` tables** (`backend/models/orm.py`) and
`backend/api/watchlist.py` (`POST/GET /watchlist`, `POST /watchlist/{id}/images`,
`DELETE /watchlist/{id}`, `GET /watchlist/sync`) — real, admin-enrolled reference photos, synced to
the edge (not precomputed embeddings — LBPH trains directly on the labeled images) at startup and
every 300s thereafter (`edge/main.py::_resync_watchlist`, same non-fatal/best-effort posture as
`_report_camera_health`/`_report_metrics` — a failed sync leaves an untrained-but-real recognizer,
never crashes the frame loop). `FaceDetectionModule` (`edge/rules/modules.py`) gained an optional
`recognizer` — a real match's `face_match_person_id`/`_name`/`_confidence` flow through
`EvidencePackager.package()` → `Event` (new migrated columns) → `EventResponse` → the Evidence
page's new "WATCHLIST MATCH" row, same end-to-end pattern as vehicle classification above.
`determine_severity()` gained a real-match case (HIGH — a matched watchlist person at a checkpoint
is a specific, serious concern, distinct from an ordinary unmatched face detection, which stays
LOW).

**Verified genuinely end-to-end, not just unit-tested in isolation:** registered a real synthetic
person via the DB layer, confirmed `GET /watchlist/sync` returned the real image, confirmed
`sync_from_backend()` trained a real LBPH model from it, confirmed `recognize()` correctly matched
the same real enrolled image and correctly rejected an unrelated one — then cleaned up the test
data. `tests/unit/test_face_recognition.py` (15 tests, real `cv2.face` — not mocked — including a
real, honestly-documented finding: LBPH's real distance on simple synthetic *shapes* isn't reliably
discriminative the way it is on real face texture, so the threshold-boundary tests control
`predict()`'s return directly rather than depending on LBPH's unpredictable behavior on non-face
synthetic imagery). `tests/unit/test_face_detection_recognition_wiring.py` (10 tests — the
integration logic in isolation via a real stand-in recognizer). `tests/unit/test_db_migration.py`
gained the new `events` columns plus real `WatchlistPerson`/`WatchlistFaceImage` schema/cascade
tests.

### 2. Real external C2 integration

**New `WebhookSubscription` table + `backend/services/webhook_delivery.py`**: a real, admin-
registered outbound webhook is delivered a real, documented JSON payload
(`WebhookAlertPayload`) whenever `backend/services/escalation.py::check_and_escalate` creates a
real `Alert` — filtered by the subscription's own `min_severity`. **Honest scope**: not a named
external standard (CAP, STIX/TAXII) this project has verified compliance against — a real,
deliberately simple JSON shape; no retry queue on failure (the subscription's own
`last_delivery_status`/`last_delivery_error` is the real, observable signal, same "show the real
state, don't just claim it works" posture as this project's chain-integrity/sync-status panels); no
delivery authentication (HMAC/mTLS) — real, disclosed future work. `backend/api/integrations.py`
adds admin-only CRUD (`POST/GET /integrations/webhooks`, `DELETE /integrations/webhooks/{id}`) plus
a real, paginated pull-based alternative (`GET /integrations/events/export`, `since`/
`min_severity`/cursor filters) for external C2 systems that don't accept inbound webhooks — returns
the same real `EventResponse` objects the dashboard itself uses, not a separate, parallel data
shape to keep honest.

**Tests:** `tests/unit/test_webhook_delivery.py` (10 tests — severity-threshold filtering in both
directions, a real success and a real simulated failure both correctly recorded on the
subscription's own delivery fields rather than raised, an inactive subscription correctly skipped,
zero subscriptions handled as a real no-op).

**Full suite: 370/370** (331 + 39 new tests added across both features in this entry).

---

## Real Alert "Close" Action — Closing the `EventState.CLOSED` Gap

**Context:** continuing the SIH PS 26187 audit, but this one is an internal completeness finding
from that same audit rather than a literal PS line item — `shared.constants.EventState` defines
`ACKNOWLEDGED` and `CLOSED` as the alert lifecycle's real final two states, and its own docstring
claimed both are "set later by command-center operator action." Grepping the whole codebase found
`ACKNOWLEDGED` genuinely is (`POST /alerts/{id}/acknowledge`) — but `CLOSED` had zero real producer
anywhere. An acknowledged alert had no further real action available; it stayed "acknowledged"
forever with no way to mark it as fully reviewed and resolved.

**New `Alert.closed_at`/`closed_by`/`resolution_notes`** (migration, same guard pattern as every
other column added this session) **and a real, queryable `Alert.lifecycle_state`**
(`shared.constants.EventState` value — `ALERTED` at creation, set by
`backend/services/escalation.py`; `ACKNOWLEDGED`/`CLOSED` set by the real acknowledge/close
endpoints) — additive alongside the existing `acknowledged_at`/`acknowledged_by`, which are
unchanged. New `POST /alerts/{id}/close` (`backend/api/alerts.py`, same RBAC as acknowledge —
OPERATOR or ADMIN) **enforces a real lifecycle order**: an alert must already be acknowledged
before it can be closed, and can only be closed once. `GET /alerts` gained `?include_closed=`
(default `false`) so the main dashboard's active-alert view doesn't stay cluttered with fully
resolved items forever, while the full history remains a real, explicit opt-in away.

**Frontend (`Alerts.jsx`):** an acknowledged, not-yet-closed alert now shows a real "Close" button
alongside its "Acknowledged by ..." line; a closed alert shows "Closed by ..." instead. The
`EventState` docstring itself was updated to point at the real code that now makes its claim true,
rather than only asserting it.

**Verified genuinely end-to-end** (not just unit-tested in isolation): ran the real
`ALERTED → ACKNOWLEDGED → CLOSED` transition directly against the local database — a real `Event`
escalated via `check_and_escalate`, then acknowledged, then closed with real resolution notes —
confirmed `lifecycle_state` reflected each real transition correctly, then cleaned up the test
data. Server restart confirmed the migration runs clean.

**Tests:** `tests/unit/test_escalation.py` gained `TestAlertLifecycleState` (2 tests — a newly
created alert's real `lifecycle_state` is `ALERTED`, with no close fields set).
`tests/unit/test_db_migration.py` gained `TestMigrationAddsAlertCloseColumns` (4 tests — the new
columns are added, a legacy row gets a real, honest `ALERTED` backfill default rather than an
arbitrary placeholder, existing rows preserved, idempotent). Full suite: 376/376 (370 + 6 new).

---

## Real Environment Audit: Two Live Crashes Found and Fixed, Real Integration/E2E Layer Added

**Context:** a fresh audit pass of the actual repository state (per the standing engineering
brief: "Do NOT rebuild from scratch — inspect, verify, then complete/harden"), starting from
running the full existing suite (confirmed 376/376 passing, matching this document's own last
entry) and then tracing one event through the real pipeline end to end.

**Two real, previously-undetected crashes were found this way, both load-bearing, both fixed:**

1. **`edge/health/camera_health.py`'s exposure check crashed on the very first real frame.**
   `hist[255][0]` / `hist[0][0]` assumed `cv2.calcHist(...)` always returns a `(256, 1)`-shaped
   array. On this project's current OpenCV build (`opencv-contrib-python-headless` 5.0.0,
   installed earlier this session for `cv2.face`/LBPH watchlist recognition), it returns `(256,)`
   instead, and `hist[255][0]` raised `IndexError: invalid index to scalar variable` —
   **confirmed directly against `demo/videos/vtest.avi`: `CameraHealthMonitor.update()` crashed
   on frame 0, every time, before this fix.** This is Gate 1, the hard camera-health override the
   entire Hybrid Reliability Engine depends on — a crash here takes down `edge/main.py`'s whole
   frame loop (`_process_frame` calls it with no surrounding try/except). Fixed to `float(hist[i])`,
   which works for both the `(256, 1)` and `(256,)` conventions. **Root cause of the gap going
   unnoticed:** `edge/health/camera_health.py` had **zero dedicated unit tests anywhere in this
   project's 376-test suite** — `tests/unit/test_reliability.py` constructs `CameraHealthReport`
   objects directly, bypassing `CameraHealthMonitor.update()`'s real frame-processing code
   entirely, so this was never actually exercised. New `tests/unit/test_camera_health.py` (9
   tests) closes that gap: the direct regression case, real over/under-exposure classification,
   frozen-frame detection, blur detection, and one test running the real monitor against the real
   video clip.
2. **`edge/rules/modules.py`'s `FaceDetectionModule._detect_haar()` crashed on the first person
   track inside a verification zone.** `_load_detectors()` already correctly logs a warning when
   `cv2.CascadeClassifier(...)` produces an empty classifier, but nothing downstream actually
   checked for that before calling `detectMultiScale()` on it — which raises a real `cv2.error`
   (`Assertion failed) !empty()`). **Root cause, also environment-specific and also newly
   introduced by the same `opencv-contrib-python-headless` swap**: that build's `cv2/data/`
   directory ships no `.xml` cascade files at all (confirmed by listing it directly — only
   `__init__.py`), unlike plain `opencv-python`. Since `retina-face` is also unavailable in this
   environment (it depends on `tensorflow`, which has no wheel for Python 3.14 — the Phase-0
   "✅ CONFIRMED" note for `retina_face` at the top of this document no longer holds and should not
   be trusted without re-checking), face detection had NO working detector in this environment at
   all, and the Haar path crashed the whole pipeline as soon as `demo/scripts/zones_config.json`'s
   real verification zone (see "Zones Grounded in Real Footage" above) saw a person — which is
   immediate, real footage of the actual demo clip. Fixed: `_detect_haar()` now checks
   `self._face_cascade is None or .empty()` and returns `None` (no detection this frame) instead
   of crashing — the same non-fatal-degradation posture already used for `psutil`, `RetinaFace`,
   and backend connectivity elsewhere in this codebase. New tests in
   `tests/unit/test_face_detection_recognition_wiring.py` (`TestHaarCascadeEmptyClassifierDoesNotCrash`,
   2 tests) lock this in with a real, controllable stand-in classifier — verified to actually
   crash against the original code before the fix, not just asserted.

**Also confirmed real, not fixed (documented in `docs/LIMITATIONS.md` instead):** `retina-face`'s
Phase-0 "CONFIRMED" status is stale (tensorflow has no Python 3.14 wheel); the Haar cascade fix
above means face DETECTION still runs (returns no detections rather than crashing), but with
neither backend actually working in this environment, face detection currently finds zero faces
regardless of input — the watchlist-matching code path is real and tested (via a real stand-in
recognizer, `test_face_detection_recognition_wiring.py`) but has nothing to recognize until either
dependency is restored.

**A real end-to-end integration/E2E layer was added, closing the gap this document and
`docs/LIMITATIONS.md` have both disclosed since the evidence-image endpoint was added ("`tests/
integration/` and `tests/e2e/` are empty for every endpoint in this codebase"):**
- `tests/integration/test_evidence_pipeline_e2e.py` — real `EvidencePackager` +
  `EvidenceChainStore` + `EvidenceEncryptor` + `EdgeKeyManager` composed together (not unit-tested
  in isolation): a clean 3-record chain verifies; a directly-tampered `previous_hash` is detected
  with the exact broken sequence number; a real Ed25519 signature verifies and a forged one
  doesn't; a real AES-256-GCM-encrypted snapshot round-trips and a tampered ciphertext file fails
  decryption; the real `CameraHealthMonitor` classifies a frozen real frame sequence as `FAILED`;
  a `FAILED`-health event is packaged with a real encrypted snapshot per the tiered-capture fix.
- `tests/integration/test_backend_e2e.py` — FastAPI's real `TestClient` against the real
  `backend.main:app` (real routers, real RBAC, an isolated per-test SQLite DB): a genuinely signed
  event ingests and verifies (`hash_valid`/`signature_valid`/`chain_valid` all `True`); a two-event
  chain verifies continuity and a forged `previous_hash` on a third event is caught; a forged
  signature and a tampered hash are each independently caught; RBAC is enforced on
  `POST /cameras` (`ADMIN` only) and alert acknowledgement (`AUDITOR` blocked, real 403); a real
  offline outbox (`edge/sync/sync_client.py`'s `SyncClient`) drains fully once synced against a
  real running `uvicorn` server on a loopback port — not a stub.
  (**Fixed a real test-isolation bug found while writing this**: `backend/main.py` does
  `from backend.database.session import SessionLocal`, a name copy at first-import time — patching
  only `backend.database.session.SessionLocal` is invisible to `lifespan()`'s own `SessionLocal()`
  calls once `backend.main` has already been imported once in the test process, silently
  bootstrapping the admin/operator/auditor accounts into a different, stale database than the one
  `init_db()` — a live attribute lookup — creates tables in. Fixed by also patching
  `backend.main`'s own copy of the name.)
- `tests/integration/test_edge_pipeline_real_video_e2e.py` — the real `edge.main.EdgePipeline`
  class itself (not a re-wiring of its components, unlike `scripts/run_false_positive_
  benchmark.py`), processing the first 200 real frames of `demo/videos/vtest.avi` end to end:
  continuity guard, adaptive compute gate, track feature tracking, calibration, the Event
  Verifier, the Hybrid Reliability Engine, and evidence packaging/chaining all run together in the
  exact order `edge/main.py` calls them, producing 11 real verified/chained evidence records and
  asserting a fully-verified hash chain plus real, non-zero performance instrumentation. Marked
  `slow` (real YOLO inference). **Bounded to 200 frames, not the full ~795, on purpose** — a real
  finding from writing this test: the full clip now runs far slower per frame than
  `docs/PERFORMANCE_REPORT.md`'s original 44.6ms/frame figure once real vehicles enter frame later
  in the clip and ANPR's EasyOCR call (CPU-heavy, added after that benchmark) starts firing —
  measured directly at a steady ~165-175ms/frame with no vehicles yet visible in the first 200.
  **Update — re-measured properly afterward**: `docs/PERFORMANCE_REPORT.md`'s "Re-measurement
  (2026-09-07)" entry confirms `scripts/run_false_positive_benchmark.py` itself still reproduces
  the original 44.6ms/21.8-FPS figure almost exactly (43.5-46.7ms, 52→23 unchanged) — because that
  script only ever wires up a subset of the real pipeline, never including `AdaptiveComputeGate`,
  `TrackContinuityGuard`, `TrackFeatureTracker`, `LineCrossingModule`, `BehaviorModule`,
  `ANPRModule`, or `FaceDetectionModule`. The real, full `EdgePipeline` genuinely costs
  ~165-175ms/frame even before ANPR fires — do not cite 44.6ms/21.8 FPS as a full-pipeline number
  anywhere it's still written. Extending the benchmark script itself to cover every real stage
  remains open (not done this pass).

**Full suite: 406/406** (376 existing + 9 evidence/health integration + 9 camera-health unit +
9 backend E2E + 2 Haar-cascade regression + 1 real bounded-frame E2E — see `docs/LIMITATIONS.md` for
exactly what the new integration layer does and does not yet cover).

---

## Assumptions and Limitations
See `docs/LIMITATIONS.md` for the full list. Key items:
1. Blockchain is MOCK MODE (WSL2/Docker unavailable on dev machine)
2. Demo runs on CPU (laptop), not Jetson-class edge hardware
3. Detection thresholds are prototype values, not calibrated from labeled data — though MOT16
   ground truth (above) has now produced a real, non-degenerate fit; it is not yet applied to
   runtime defaults, and the two real sequences tried disagree with each other
4. Face recognition IS implemented (real `cv2.face.LBPHFaceRecognizer` watchlist
   matching — see "Real Facial Recognition and External C2 Integration" above), but is
   classical (LBPH, not a modern embedding model), has no liveness detection, and a
   match is a lead for human review, never a confirmed identification on its own — this
   item was stale (predated that work) until this pass; do not re-introduce the "NOT
   attempted" claim without checking `edge/detection/face_recognition.py` first
5. ANPR scoped to checkpoint-angle cameras only
6. Clock drift check uses NTP-synchronized system clock (opportunistic)
7. Cross-camera corroboration is temporal/spatial plausibility only, not person
   re-identification — see `backend/services/cross_camera.py`
8. Face detection currently finds zero faces on this dev machine, regardless of input —
   `retina-face` cannot install (needs `tensorflow`, no Python 3.14 wheel) and this
   environment's OpenCV build (`opencv-contrib-python-headless`, needed for `cv2.face`)
   ships no Haar cascade XML data files. The crash this used to cause is fixed (see "Real
   Environment Audit" above); real face detection needs one of those two dependencies
   restored, or a cascade XML file added to the repo, to actually detect anything
9. `tests/integration/`/`tests/e2e/` are no longer empty (see "Real Environment Audit"
   above), but still don't cover the evidence-image/evidence-key HTTP routes or the
   WebSocket endpoints — see `docs/LIMITATIONS.md`
