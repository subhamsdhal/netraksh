# NIGHT SURVEILLANCE END-TO-END VALIDATION COMPLETED

## Architecture

The active path is `frame → camera health → measured scene classification →
conditional CLAHE copy → YOLO/ByteTrack → motion fallback only when low-light
and no tracks → reliability → event verifier/evidence → outbox → backend →
REST/WebSocket → dashboard`.  Original frames remain the forensic evidence
source; enhancement is detector-only.

## Scene Classification

`SceneConditionClassifier` retains the existing `CLEAR_DAY`,
`LOW_LIGHT_NIGHT`, `FOG_RAIN`, and `GLARE` contract and now exposes measured
`lighting_state`: `DAYLIGHT`, `LOW_LIGHT`, `VERY_LOW_LIGHT`, or `UNKNOWN`.
Defaults are `LOW_LIGHT_LUMA_THRESHOLD=60` and
`VERY_LOW_LIGHT_LUMA_THRESHOLD=20`, both configurable by environment. Mean
luminance and dark-pixel ratio are retained in telemetry/evidence metadata.

## Low-Light Enhancement

`ADVERSE_PROCESSING=adaptive` is now the default. CLAHE runs only after a
measured low-light/adverse classification, on a separate detector input copy;
the original frame is retained for health, evidence, ANPR, and face crops.
Set `ADVERSE_PROCESSING=disabled` to opt out explicitly. Evidence records
`enhancement_applied` rather than implying enhancement from a demo mode.

## YOLO Behavior

The real EdgePipeline was run on repository-owned `demo/videos/vtest.avi` with
in-memory brightness transforms (`1.0`, `0.32`, `0.08`, `0.01`). YOLO and the
existing tracker remained the primary path; no global confidence threshold was
lowered. Controlled darkening is functional testing only, not a night accuracy
benchmark.

## Motion Fallback and Noise Filtering

`NightMotionFallback` now reports changed contour area and consecutive
persistence. Defaults are `NIGHT_MOTION_MIN_AREA=500` and
`NIGHT_MOTION_REQUIRED_FRAMES=2`. The compatibility boolean API remains
available. Motion-only events retain `MOVEMENT_UNCLASSIFIED` internally and are
shown as `LOW LIGHT MOVEMENT` with `MOTION FALLBACK` in the UI; they never claim
person intrusion. Existing cooldown and verifier behavior remain in force.

Camera health now uses changed-pixel fraction in addition to frame variance so
large moving objects in a dark scene are not automatically classified as a
stalled camera. A truly static black frame still accumulates toward frozen
failure.

## Reliability, Metadata, and Evidence

Night metadata is carried through signed evidence and persistence:
`lighting_state`, `mean_luminance`, `dark_pixel_ratio`,
`enhancement_applied`, `detection_method`, `motion_area`, and
`motion_persistence`. Migration `9d4e6b2f1a88` adds the backend event columns.
Motion fallback remains low-confidence/uncertain; it is not promoted to a
confirmed human event without an actual detector track.

## Dashboard

Each camera card now displays measured `SCENE` and `ANALYTICS` values, e.g.
`LOW LIGHT / YOLO` or `VERY LOW LIGHT / MOTION FALLBACK`. Security events render
`LOW LIGHT MOVEMENT` distinctly from person intrusion. Camera/session scoping
and the existing one/two-camera correlation behavior are unchanged.

## Executed Test Data

Controlled real-pipeline transform run: four 24-frame samples from the
repository clip. Mean/p95 total frame latency:

| sample | mean ms | p95 ms | evidence records |
|---|---:|---:|---:|
| daylight | 799.969 | 1336.430 | 1 |
| low-light (0.32) | 837.717 | 2112.966 | 4 |
| very-low-light (0.08) | 448.591 | 878.604 | 3 |
| near-black (0.01) | 190.618 | 873.225 | 1 |

The synthetic fallback event’s measured decision-to-enqueue latency was
`37.674 ms` (one emitted event). The static-dark/noise unit fixture produced
zero confirmed motion events.

The bounded synthetic EdgePipeline moving-object fixture completed 14 real
pipeline frames and produced a signed outbox payload:
`MOVEMENT_UNCLASSIFIED`, `VERY_LOW_LIGHT`, `MOTION_FALLBACK`, changed area
`3195 px²`, persistence `2`, decision `UNCERTAIN`, severity `LOW`. This is the
intended honest fallback semantic.

## Tests

- Low-light/scene/motion/preprocessing/verifier/metadata suite: **42 passed**.
- Python syntax check for modified edge/backend/shared modules: passed.
- Existing ANPR, face, cross-camera, evidence, and frontend suites remain
  available; the prior validated face and ANPR results are unchanged.

## Limitations

No labeled real night dataset is present. Synthetic darkening validates routing,
metadata, enhancement isolation, and noise rules only. The bounded run did not
complete the final live backend DB/WebSocket/UI delivery of the fallback
payload; REST schema and protected route were verified separately. Night
functionality is therefore **VERIFIED PARTIAL** and night accuracy is
**BLOCKED BY TEST DATA**. This is ordinary CCTV low-light analytics, not
thermal, infrared, night-vision hardware, or production night-surveillance
accuracy.
