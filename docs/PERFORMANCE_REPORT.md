# NETRAKSH — Performance Report

**Status: MEASURED — one real run completed and recorded below.**

Every number in this file came from `scripts/run_false_positive_benchmark.py` actually executing
against real footage on the machine described below — none of it is estimated, and none of it is
projected onto different hardware. See `docs/PERFORMANCE_REPORT_MEASURED.json` for the raw output
this table was transcribed from (not hand-edited).

**Read the "What this run actually shows" section below before quoting these numbers in the PPT** —
the honest interpretation matters as much as the figures themselves.

## How this report was produced

Unlike the original template's instructions (run `edge/main.py` live), this run used
`scripts/run_false_positive_benchmark.py` — a measurement harness built specifically for this report
that exercises the *same* production classes `edge/main.py` uses (`CameraHealthMonitor`,
`SceneConditionClassifier`, `CalibrationModule`, `DetectionTracker`/YOLO, `VirtualFenceModule`,
`make_reliability_decision`, `EventVerifier`, `PipelineMetrics`) frame-by-frame against a real video
file, without the side effects of full evidence packaging/sync (no keys or DB files written). This was
necessary because no demo video existed in this repository and no live camera/staged scenario was
available at the time this was run — see the Test run metadata note on video provenance.

## Test run metadata

| Field | Value |
|---|---|
| Date | 2026-09-04 |
| Machine | Windows 11 Home, Intel64 Family 6 Model 154 Stepping 3 (GenuineIntel), 16 logical CPUs, 15.6 GB RAM, CPU-only (no GPU used) — Python 3.14.7, ultralytics 8.4.137, torch 2.13.0+cpu, opencv-python 4.14.0 |
| Video source | `demo/videos/vtest.avi` — OpenCV's own official sample pedestrian-tracking test clip (fetched from `github.com/opencv/opencv`, `samples/data/vtest.avi`), 768×576, 10 fps, 795 frames (~79.5s). **Not footage of the team's actual demo camera or scenario** — used because no demo video or staged scenario existed at the time of this run. Re-run this benchmark against real staged footage before final submission if possible; see `docs/LIMITATIONS.md`. |
| Zone tested | One rectangular fence zone, normalized coordinates `(0.456, 0.260)`–`(1.0, 0.521)` — visually placed over the main pedestrian walkway visible in the clip, not the placeholder zones shipped in `demo/scripts/zones_config.json` |
| Duration | 795 frames / 79.5s of source video, processed twice (once per confirmation policy) |
| Scene conditions covered | CLEAR_DAY only (daytime courtyard footage) — LOW_LIGHT_NIGHT/FOG_RAIN/GLARE are **not** covered by this run |

## None of this report's real crossings are actual intrusions — checked directly, not assumed

Read this before treating any DETECTED/UNCERTAIN rate in this document as a proxy for real-world
intrusion-detection accuracy: it is not one, and this was verified concretely rather than left as an
inference from the zone-placement note above.

Investigating frame 694 — the single most closely-examined candidate in this whole report, across every
condition tested — confirms it directly: the frame's actual taped-off/coned restricted area (real
white/red tape and cones, clearly visible in every snapshot) is a SEPARATE dirt/mulch patch elsewhere in
frame. The zone tested throughout this document covers the open, paved plaza instead, where multiple
ordinary pedestrians casually cross in every direction simultaneously in the same single frame. The
specific tracked person is a real, correctly-detected individual walking calmly and directly across an
open public walkway — confirmed quantitatively: real path smoothness `0.878` and speed consistency
`0.746` over a sustained 38-point trajectory, nothing erratic, evasive, or unusual about the movement.

**This generalizes to the entire real-data calibration effort in this document, not just this one
candidate.** Every "genuine crossing" collected and manually reviewed — 500+ candidates across
daytime, night, fog, glare, and every compound/mild variant — is real in the sense that a real,
correctly-detected person genuinely crossed the marked polygon boundary. None represent trespass, forced
entry, evasion, or any other genuine security-relevant intrusion pattern; they are ordinary foot traffic
through a normal campus walkway, chosen specifically because it reliably produces a high volume of real,
benchmark-quality crossings for calibration purposes.

**What this report's real-data work honestly validates:** the Hybrid Reliability Engine's D/T/S/H
scoring mechanics respond correctly to real image degradation, real double-penalties, and real edge
cases (occlusion, blur, compound conditions), using genuine, non-fabricated object detections — a
real, substantial body of engineering validation. **What it does NOT and cannot validate:** whether the
system correctly flags genuine border/security intrusions, since no such scenario — staged or real —
exists anywhere in the tested footage. Every DETECTED/UNCERTAIN percentage in this document should be
read as "how reliably does the Reliability Engine flag a real, non-spurious object crossing this
polygon," not as "how well does this system catch intruders."

## Frame-level pipeline latency (ms)

From the "with verifier" (shipped-defaults) pass — the other pass's numbers are materially identical
(within measurement noise) and are in `docs/PERFORMANCE_REPORT_MEASURED.json`.

| Stage | n | mean | p95 | max |
|---|---|---|---|---|
| health_condition_ms | 500 | 9.54 | 10.58 | 13.43 |
| detection_tracking_ms | 500 | 34.93 | 39.16 | 59.08 |
| event_processing_ms | 500 | 0.09 | 0.13 | 0.18 |
| total_frame_ms | 500 | 44.55 | 49.17 | 69.38 |

Measured FPS (same run): **21.76** (real-time-capable at this video's native 10 fps, on CPU only, no
GPU, no TensorRT — YOLOv8n's detection+tracking stage is the dominant cost at ~35ms mean, as expected).

Note: `PipelineMetrics`'s rolling window caps at 500 samples, so `n=500` here means "the last 500 of
795 frames processed," not "295 frames were dropped" — nothing is missing, this is that field's
documented rolling-window behavior.

## Event-level pipeline latency — decision to enqueued (ms)

**Not measured in this run.** This benchmark harness deliberately does not exercise
`EvidencePackager`/`SyncClient` (to avoid writing real keys/DB files during a benchmarking run), so no
event-level timing was recorded here — this is a real gap in this specific report, not a hidden
number. Event-level latency (snapshot → hash+sign → chain-store → enqueue) was previously measured in
isolation during development (see `docs/ARCHITECTURE.md`'s Performance Instrumentation changelog
entry) but not as part of this same run. Re-run `edge/main.py` directly (not this benchmark script)
against real footage to get this table populated from the same run as the numbers above.

## Resource usage

| Metric | Value |
|---|---|
| CPU % | 0.0 (as reported by `psutil.Process().cpu_percent()`) — **this reading is not credible** for a process that just spent ~35 real seconds doing YOLO inference on CPU, and should not be quoted. Likely cause: a single end-of-run sample doesn't capture sustained usage the way a periodic sampler would; `edge/main.py`'s own periodic `_report_metrics()` (every 10s during a live run) is the credible way to get this number. Do not put "0% CPU" in the PPT. |
| RSS (MB) | 412.9 (without-verifier pass) / 426.5 (with-verifier pass) — this reading is plausible (matches a loaded YOLOv8n + OpenCV + Python process) and can be quoted as "~410-430 MB resident memory" |

## False-positive reduction — before/after the Event Verifier (architecture v4 §11)

| | Raw candidate events fired | Alerts actually raised |
|---|---|---|
| Without verifier (1 confirmation) | 52 | 23 |
| With verifier (shipped defaults, 3 confirmations) | 52 | 23 |

### What this run actually shows — read before quoting a percentage

**The Event Verifier made no measurable difference on this specific clip: 23 alerts either way.**
This is a real, honest result, and it is **not** the "temporal verification cuts false alarms"
headline number the team may have expected — say so plainly if asked, rather than reaching for a
different framing after the fact.

What actually happened, diagnosed from the same run:
- **The Hybrid Reliability Engine did real, substantial filtering:** 52 raw fence-crossing candidates
  → only 23 (44%) ever had even one frame where `R ≥ 0.75`. The other 29 candidates never cleared the
  Reliability Gate at all, on any frame, and expired unconfirmed regardless of confirmation policy.
  This is a genuine, measured demonstration of the Reliability Gate's filtering effect — just not the
  feature this table was designed to isolate.
- **Of the 23 candidates that did clear the Reliability Gate at least once, every single one stayed
  reliably detected for 3+ consecutive frames.** None were "confirmed once, then lost" — this
  particular clip's tracking is clean enough (daytime, unoccluded, well-lit pedestrians) that it
  contains none of the single-frame jitter the Event Verifier exists to catch. The Verifier cost
  nothing here (no true positives lost) but also had nothing to prove itself against.
- **Conclusion for the PPT:** report this honestly as "on a clean daytime clip, reliability filtering
  removed 56% of raw candidates before they could become alerts, and temporal verification added zero
  additional cost." Do **not** claim a false-positive reduction from verification using this data —
  that claim needs footage that actually contains tracking jitter (a lower frame-rate or more
  occluded/crowded clip, or the same clip re-tested with a deliberately shortened `track_buffer` to
  induce ID switches) to be honestly measurable. This is a real, open next step, not a solved one.

### Re-run against real, denser footage — the open next step above, now closed

The gap identified directly above ("needs footage that actually contains tracking jitter") is
exactly what MOT16-04 (Milan et al., CC BY-NC-SA 3.0 — the same real dataset already sourced this
session for `CalibrationModule`'s first real fit) provides: a dense, real Tokyo pedestrian street at
1920×1080, real occlusion, real crowding — nothing like `vtest.avi`'s clean daytime courtyard. Real
run, same harness (`scripts/run_false_positive_benchmark.py`), 1050 real frames reconstructed into a
video via `cv2.VideoWriter` from the real MOT16-04 image sequence, zone picked by eye from an actual
frame (see `docs/PERFORMANCE_REPORT_MOT16_MEASURED.json` for the raw output):

| | Raw candidate events fired | Alerts actually raised |
|---|---|---|
| Without verifier (1 confirmation) | 18 | 14 |
| With verifier (shipped defaults, 3 confirmations) | 18 | 12 |

**A real, measured reduction this time: 14.3% fewer alerts (14 → 12) from the same 3-confirmation
Event Verifier policy — on footage dense/occluded enough for the effect to actually show up.** This
is not the same clip re-run with a different label; it's a genuinely different, denser real dataset
producing a genuinely different, real result, consistent with the diagnosis above (the earlier
"zero difference" was correctly attributed to `vtest.avi` being too clean to exercise the Verifier,
not to the Verifier not working).

**Caveats, stated as plainly as everything else in this report:** MOT16-04 is real external CCTV
footage, not the team's own staged demo scenario — see `docs/LIMITATIONS.md`'s entry on why real
staged footage still doesn't exist and can't be fabricated. n=18 raw candidates on one video is a
small sample; a single 14→12 swing is a real, honest result, not a statistically robust one. The
zone (a dense central pedestrian plaza, picked by eye from frame 500) is this project's own
interpretive choice, not a MOT16-provided ground-truth region. Treat this as "real evidence the
Event Verifier does something on the kind of footage it was designed for," not as a definitive
false-positive-reduction percentage to quote without this context.

## Reliability Engine behavior under real night/fog/glare conditions

A separate, real measurement — **different methodology from the table above, do not merge the two
numbers.** The table above uses `scripts/run_false_positive_benchmark.py`, which tracks whether R
clears `RELIABILITY_R_THRESHOLD` on *any* frame across each candidate's whole tracked lifetime. The
numbers below use `scripts/collect_calibration_data.py` + `scripts/analyze_reliability_under_conditions.py`,
which compute R once, at the single frame the fence-crossing event actually fires on — a stricter,
single-frame measurement. Both are real; they answer different questions and are not comparable
head-to-head.

This measurement exists because of an attempt to calibrate the Hybrid Reliability Engine's weights
from real labeled data (see `docs/LIMITATIONS.md`'s Hybrid Reliability Engine entry): manual review of
every real fence-crossing candidate in `demo/videos/vtest.avi` found zero false positives, in daytime
**and** under three honest, disclosed synthetic night/fog/glare lighting transforms applied to the same
real footage (`--synthetic-condition night|fog|glare` — see `scripts/collect_calibration_data.py`'s
docstring for exactly what is and isn't synthetic here). With every labeled candidate genuine,
weight-fitting was correctly refused — but the same labeled data answers a different, real, and more
operationally important question: **of these genuine crossings, how many does the CURRENT hand-picked
formula actually mark UNCERTAIN instead of DETECTED?**

| Condition | Genuine (label=1) candidates | DETECTED (R ≥ 0.75) | UNCERTAIN (real crossing missed) |
|---|---|---|---|
| Daytime (real, unmodified video) | 52 | 52 (100%) | 0 (0%) |
| Synthetic night (real video, real Gaussian-darkened frames) | 51 | 47 (92%) | 4 (8%) |
| Synthetic fog (real video, real haze-blended + blurred frames) | 52 | 49 (94%) | 3 (6%) |
| Synthetic glare (real video, real brightened + clipped frames) | 55 | 33 (60%) | 22 (40%) |

**These numbers are after SIX real, separate fixes, applied in sequence** — each honestly
re-measured, none a full solution on its own:

1. **Fix 1 — H double-penalty** (`edge/reliability/decision.py::_health_quality_score`). The
   original, first-measured result was 0/52 (0%) DETECTED under fog, i.e. every single genuine
   crossing marked UNCERTAIN. Diagnosis: two supposedly-independent factors were actually
   double-counting the same real signal — `S` (scene quality) genuinely drops because fog reduces
   contrast, **and** `H` (health quality) was *also* dropping to 0.5 because the same real blur that
   simulates fog haze genuinely trips the Camera Health Monitor's Laplacian blur detector into a
   DEGRADED reading. That reading is correct in isolation (the frame really is blurrier), but H's
   actual purpose is to flag a broken/dirty/defocused *camera* — not weather the scene classifier
   already has its own dedicated signal for. The fix: `_health_quality_score` now scores H as healthy
   (1.0) specifically when health is DEGRADED for `EXCESSIVE_BLUR` *and* the scene is already
   independently classified `FOG_RAIN` or `LOW_LIGHT_NIGHT` — any other DEGRADED reason, or blur
   during `CLEAR_DAY`, still fully penalizes H exactly as before (see
   `tests/unit/test_reliability.py::TestWeatherExplainedBlurDoesNotDoublePenalize`, 4 tests). This
   alone raised fog from 0% to 71% DETECTED.
2. **Fix 2 — S's contrast reference for FOG_RAIN** (`edge/reliability/decision.py::_scene_quality_score`).
   Even after fix 1, 29% of genuine fog crossings still missed threshold, because `contrast_score`
   judged every FOG_RAIN frame against `_SCENE_CONTRAST_GOOD` (60.0) — a clear-day ideal a scene
   classified FOG_RAIN can never meet, since `contrast_std < FOG_CONTRAST_THRESHOLD` (30.0) is
   literally the real rule `SceneConditionClassifier` already uses to call a scene foggy in the first
   place (`edge/condition/scene_condition.py`). Judging it against 60 anyway scored every fog frame as
   "badly foggy" even when it was merely "typically foggy for what got it classified as fog at all."
   The fix reuses that same, already-existing `FOG_CONTRAST_THRESHOLD` constant as FOG_RAIN's own
   contrast reference instead of introducing a new number — a frame at the real classification
   boundary now scores full contrast marks, and one meaningfully foggier than that still scores
   proportionally lower (see
   `tests/unit/test_reliability.py::TestSceneQualityFogContrastReference`, 4 tests). This left night
   unaffected at this stage (21/51 before and after fix 2) — night's own bottleneck is fix 3, below.
   This raised fog further, from 71% to 87% DETECTED.
3. **Fix 3 — S's brightness reference for LOW_LIGHT_NIGHT** (same function, same pattern as fix 2).
   Night's real measured driver was `brightness_score`, not contrast — every frame classified
   `LOW_LIGHT_NIGHT` is, by definition, below `BRIGHTNESS_NIGHT_THRESHOLD` (60.0, the real rule
   `SceneConditionClassifier` already uses to call a scene night in the first place), yet
   `brightness_score` judged it against the `CLEAR_DAY` midpoint ideal (128.0) meant for a symmetric
   too-dark/too-bright measurement — scoring every night frame as "badly dark" even at the very
   boundary of "still counts as night." The fix reuses `BRIGHTNESS_NIGHT_THRESHOLD` the same way fix 2
   reused `FOG_CONTRAST_THRESHOLD`: within the night band, more light is unambiguously better (not
   "distance from an ideal"), so a frame right at the classification boundary now scores full
   brightness marks, and a darker one than that still scores proportionally lower (see
   `tests/unit/test_reliability.py::TestSceneQualityNightBrightnessReference`, 4 tests).
   `FOG_RAIN`/`CLEAR_DAY`/`GLARE` are untouched (confirmed: fog's DETECTED rate is identical before and
   after fix 3, 45/52 both times). This raised night from 41% to 61% DETECTED.
4. **Fix 4 — S's contrast reference for LOW_LIGHT_NIGHT** (same function). Fix 3 left 39% of genuine
   night crossings still missing, driven by `contrast_score` still judging night frames against the
   clear-day contrast ideal (60.0). **This case is different in kind from fixes 2 and 3**, disclosed as
   such: `SceneConditionClassifier`'s `LOW_LIGHT_NIGHT` rule checks brightness only — there is no
   existing "this is the real rule that made it night" constant for contrast to reuse the way `FOG_RAIN`
   and night's own brightness fix could. `_SCENE_CONTRAST_GOOD_NIGHT` is therefore a genuinely NEW,
   hand-picked heuristic (half of `BRIGHTNESS_NIGHT_THRESHOLD` = 30.0) — not calibrated, not a reused
   classification boundary — justified on a real, statable physical basis: `contrast_std` measures the
   spread of a non-negative pixel-value distribution, and one whose mean is capped below
   `BRIGHTNESS_NIGHT_THRESHOLD` cannot have much spread without clipping at zero, so a legitimately-
   dark-but-not-defective night frame's achievable contrast is bounded by its own brightness headroom,
   not the clear-day sensor's full range. This is exactly the same category of hand-picked default as
   the *original* `_SCENE_CONTRAST_GOOD`/`_SCENE_BRIGHTNESS_IDEAL`/`_SCENE_GLARE_BAD` constants
   themselves — disclosed as such, not oversold as a "reused real constant" the way fixes 2 and 3
   legitimately are (see
   `tests/unit/test_reliability.py::TestSceneQualityNightContrastReference`, 4 tests, including a
   regression lock confirming `FOG_RAIN`'s own contrast reference is unaffected). This raised night
   further, from 61% to 76% DETECTED.
5. **Fix 5 — a real, previously-shipped PRODUCTION bug, not a calibration-side issue like fixes 1-4.**
   Found while investigating why 3/52 DAYTIME crossings still missed threshold despite S≈0.92 and
   H=1.0 — no scene or health issue to blame at all. `TrackFeatureTracker`
   (`edge/temporal/track_features.py`) only ever registered a track's `_first_seen` time inside
   `compute()` — and both `edge/main.py` (the real, deployed pipeline) and
   `scripts/collect_calibration_data.py` only ever call `compute()` from an EVENT-triggered branch (a
   fence-crossing handler, firing once per track at the crossing transition). That means
   `_first_seen[track_id]` got registered at the moment of a track's FIRST qualifying event, not its
   real first-observed frame — so `age_seconds` was always `0.0` on that one call, regardless of how
   long the track had genuinely already existed. Measured directly, not assumed: the 3 daytime
   candidates each had 34-50 real trajectory points (1.4-2 real seconds of prior tracking) yet
   `T_age_score` (a new diagnostic field this investigation added to the manifest) was exactly `0.0`
   for all three. The fix: a new `TrackFeatureTracker.observe()` method, called unconditionally for
   every active track every frame in both `edge/main.py` and the collection script — independent of
   whether any rule event fires that frame — so age is registered the moment a track is truly first
   seen (see `tests/unit/test_track_features.py::TestObserveFixesEventTriggeredAgeZeroing`, 4 tests;
   full suite 227/227). This bug was condition-independent, so re-measuring improved ALL THREE
   datasets at once: daytime rose from 94% to **100%** (all 3 residual candidates now resolved);
   night rose from 76% to 92%; fog rose from 87% to 94%. By a wide margin the largest single fix this
   session — it corrects a genuine defect in the real, deployed edge pipeline's temporal-scoring
   wiring, not just a calibration-script heuristic.
6. **Fix 6 — the SAME H double-penalty as fix 1, generalized, for GLARE.** A synthetic glare
   transform (`--synthetic-condition glare`: scale pixels ×1.8+20, clip at 255) reliably classified
   `GLARE` via the real `glare_fraction` path (~0.43, well past the real 0.15 cutoff). Manual review
   of all 55 real candidates again found zero false positives, and the SAME real double-penalty
   pattern as fog appeared: glare genuinely blows out highlights, which `S` already penalizes via
   `glare_fraction`, **and** the same real overexposure genuinely trips the Camera Health Monitor's
   own exposure-clipping check (`clip_fraction`, fraction of pixels at exactly 255 — measured at
   30-41% here, far past its 0.10 threshold) into `ABNORMAL_EXPOSURE`, initially measuring 0/55 (0%)
   DETECTED — identical in shape to fix 1's original finding. Rather than special-case this
   separately, fix 1's exemption was generalized into a real
   `_WEATHER_EXPLAINED_DEGRADED_REASONS` mapping (`edge/reliability/decision.py`) —
   `{EXCESSIVE_BLUR: {FOG_RAIN, LOW_LIGHT_NIGHT}, ABNORMAL_EXPOSURE: {GLARE}}` — so a third such
   pairing, if ever found, is a one-line addition (see
   `tests/unit/test_reliability.py::TestWeatherExplainedExposureDoesNotDoublePenalize`, 4 tests; full
   suite 239/239). Re-measured: glare rose from 0/55 (0%) to **33/55 (60%) DETECTED**.

**What this does NOT mean:** it does not mean fog, night, or glare detection is now "solved" — 6% of
genuine fog crossings, 8% of genuine night crossings, and 40% of genuine glare crossings under these
specific synthetic intensities still miss, a real, honest, remaining gap (daytime, notably, is now
fully resolved at 100% — the remaining gap is entirely in the three synthetic degraded-condition
datasets). It also does not mean any synthetic transform's specific intensity (night: scaling pixel
values by 0.28 plus Gaussian noise; fog: `cv2.addWeighted` at 0.42/0.58 plus a 7×7 Gaussian blur;
glare: scaling by ×1.8+20 with clipping) is representative of every real night/fog/glare condition
NETRAKSH might face — this project has no real footage in any of these three conditions to calibrate
any transform's intensity against, or to validate fix 4's specific heuristic value against, the way
fixes 2, 3, and 6 could each lean on an already-existing, independently-justified constant (see
`docs/LIMITATIONS.md`). This is real, open, partially-addressed work, not a fully solved one.

**Night's residual, investigated specifically:** unlike fixes 1-5, no further formula bug was found —
an honest negative result, not an unexamined gap. All 4 remaining UNCERTAIN night candidates are
genuine, correctly-detected people (each snapshot manually re-checked). `S` is nearly flat across all
51 night candidates (0.6815-0.6961 — this synthetic darkening is uniform per-frame), so `D` (raw
detector confidence) is what actually separates them: sorting all 51 by `D` shows a clean, monotonic
boundary — the 4 lowest-`D` candidates (0.48-0.63, vs a 0.78 mean) are *exactly* the 4 that miss
threshold, with `R` increasing smoothly right through 0.75. This is the Reliability Engine correctly
expressing more caution on the objectively weakest evidence in the dataset, not a defect — see
`docs/LIMITATIONS.md` for why this is left open rather than force-fixed.

**That conclusion was then actually tested with a milder night transform, the same way as fog's and
glare's.** `--synthetic-condition night_mild` (scale ×0.45 vs the original ×0.28) was empirically
tuned against 5 frames spanning the whole video to measure `brightness_mean≈53` — still reliably
`LOW_LIGHT_NIGHT` (a consistent ~7-point safety margin under 60 throughout) but much closer to the
boundary than the original's ~33. All 52 candidates again reviewed — zero false positives.

| Night intensity | Genuine candidates | DETECTED | UNCERTAIN |
|---|---|---|---|
| Original (`brightness_mean≈33`) | 51 | 47 (92%) | 4 (8%) |
| Milder (`brightness_mean≈53`) | 52 | 50 (96%) | 2 (4%) |

A smaller improvement than fog's (94%→98%) or glare's (60%→88%), consistent with night having already
had more of its structural gap closed by the two earlier reference-point fixes (fixes 3 and 4) before
this test — less headroom remained for a milder transform to recover. The 2 remaining `night_mild`
residuals (`D=0.47` and `D=0.49`, both far below the 0.78 mean, `T`/`S`/`H` all near-max) are the same
genuine low-confidence-detection pattern as every other residual this session.

**The same paired daytime comparison used for `fog_mild`'s and `glare_mild`'s residuals, applied here,
told a third, real, distinct story.** Matching 41 of 52 candidates to a daytime candidate at the same
`frame_idx`:

| Residual | Matched drop (daytime D − night_mild D) |
|---|---|
| Frame 694 (same crossing as `fog_mild`'s AND `glare_mild`'s outliers) | 0.262 |
| candidate_032 (nearest-frame match, 1-frame offset, different person) | ≈0.246 |

Frame 694 is, again, the same real crossing flagged as the largest outlier under both `fog_mild` (0.386)
and `glare_mild` (0.309). **This is now the THIRD independent condition — three genuinely different
kinds of visual degradation (haze/blur, brightening/washout, darkening) — in which this exact same real
person shows the largest confidence drop.** A strong, cross-validated conclusion: this one real
crossing is universally the hardest real detection in this entire dataset, independent of which
degradation is applied. The second residual (a different person, no exact frame match) shows a
comparably large drop (≈0.246) too. **Unlike `glare_mild` (only 1 of 6 residuals showed a real
condition-specific confidence collapse; the other 5 were ordinary moderate-confidence detections tipped
by `S`'s uniform penalty), BOTH of `night_mild`'s residuals are genuinely, substantially
night-degraded** — a real, honest difference in character between night's and glare's residual
populations, not a coincidence of small sample size.

## The compound-condition datasets, and a methodological correction caught along the way

The same paired comparison was extended to the compound-condition datasets — and caught a real mistake
before it was published. Frame-`idx` matching between two datasets is a useful heuristic, but is NOT
guaranteed to be the same real track: when several people cross near the zone at similar times, a
different physical person can fire the fence-crossing event at the same `frame_idx` in two separately-
run datasets. Caught directly: `night_fog` and `fog_glare` both flagged a candidate at frame 242 with an
apparent large drop (`≈0.265` against daytime's own frame-242 candidate) — but visually comparing the
snapshots shows daytime's frame-242 candidate is a DIFFERENT person (mid-zone, near the sign) than the
small, distant figure `night_fog`/`fog_glare` actually flag (top-right corner). `night_fog` and
`fog_glare` genuinely agree with EACH OTHER (identical figure, identical position) — just not with
daytime's own frame-242 candidate. **That specific comparison is retracted as spurious.** Every other
comparison reported in this document — including every frame-694 instance — was individually visually
re-verified (identical scene composition, bounding-box position, and surrounding people) before being
reported, precisely because this false match was found.

With that correction in place:

| Dataset | Residuals | Frame 694 present? | Pattern |
|---|---|---|---|
| `fog_glare` | 15 | Yes — drop `0.265`, largest in the dataset (visually confirmed) | Mostly small-moderate real drops (0.003-0.106); frame 694 the one standout |
| `night_glare` | 7 | No | Small real drops only (max 0.087, one -0.035) — ordinary borderline detections |
| `night_fog` | 2 (n=7) | Inconclusive (frame-242 match retracted) | Too small a sample to characterize further |
| `night_fog_glare` | 0 (n=3) | — | Nothing to investigate |
| `night_fog_glare_mild` | 4 | Yes (already documented above) | Consistent with the overall picture |

`fog_glare`'s frame 694 match is a FIFTH independent, visually-confirmed instance of this one crossing's
universal fragility — now spanning every single-condition transform tested this session plus at least
one real compound. `night_glare`'s residuals, by contrast, show only small real drops, consistent with
its already-healthy 87% DETECTED rate and residuals that are ordinary borderline detections — the same
character as most of `glare_mild`'s residuals.

**Fog's residual, investigated the same way, reaches the identical conclusion:** all 3 remaining
UNCERTAIN fog candidates are genuine, correctly-detected people (small/distant figures visibly
softened by the haze/blur transform). `S` is nearly flat across all 52 fog candidates
(0.8126-0.8295), so `D` again separates them cleanly: the 3 lowest-`D` candidates (0.52-0.56, vs a
0.76 mean) are *exactly* the 3 that miss threshold, `R` increasing smoothly through 0.75. No formula
bug found — left open for the same reason as night.

**That "no bug, just transform severity" conclusion was then actually tested with a milder fog
transform, not left as an assumption.** `--synthetic-condition fog_mild` (blend 0.55/0.45 with a
smaller 5x5 blur, vs the original 0.42/0.58 with 7x7) was empirically tuned against 5 frames spanning
the whole video to measure `contrast_std≈28` — still reliably `FOG_RAIN` (~2-point margin under the
real 30 threshold throughout) but right at the boundary, not deep inside it. All 52 candidates again
reviewed — zero false positives.

| Fog intensity | Genuine candidates | DETECTED | UNCERTAIN |
|---|---|---|---|
| Original (`contrast_std≈21`) | 52 | 49 (94%) | 3 (6%) |
| Milder (`contrast_std≈28`) | 52 | 51 (98%) | 1 (2%) |

A real, honest confirmation: milder fog genuinely produces fewer misses, so at least part of the
original 6% residual really was a transform-severity effect, not purely irreducible evidence-based
caution — an important nuance the "no bug found" conclusion above didn't fully capture on its own. The
single remaining `fog_mild` residual (`D=0.37`, far below the 0.77 mean, `S=0.92`/`H=1.0`/`T=0.85` all
near-max) is the same genuine low-confidence-detection pattern as every other residual this session —
visually confirmed as a real person, no bug.

**This residual was then compared directly against unmodified daytime footage of the exact same real
moment** — a real, paired before/after measurement, not just "D happens to be low." Frame 694 has a
real, matched candidate in both the daytime (`D=0.756`) and `fog_mild` (`D=0.369`) datasets — visually
confirmed as the same real person, same real crossing (identical scene layout and bounding-box
position). Systematically matching all 52 `fog_mild` candidates to a daytime candidate at the exact
same `frame_idx` (42 of 52 matched):

| | Confidence drop (daytime D − fog_mild D) |
|---|---|
| This residual (frame 694) | **0.386** |
| Next-largest drop (of the other 41) | 0.035 |
| Mean drop (other 41) | 0.005 |

`fog_mild`'s real effect on detection confidence is not a uniform mild degradation across all real
crossings — it is heavily concentrated in this one outlier, roughly 10x the next-largest drop. An
initial visual pass suggested a similar-colored background (tree branches/mulch) as the explanation —
but a rigorous investigation (re-extracting the exact bounding box from the drawn snapshot, pulling the
raw frame directly from the video, and inspecting the surrounding sequence, frames 691-696) found the
real cause, and it's more precise: **frame 694 is the peak instant of a real, transient partial
occlusion between two real pedestrians.** A second, taller person (dark jacket) walks almost directly
behind/past the tracked person (blue jacket); across the sequence his raised leg swings up and, at
exactly frame 694, visually overlaps the tracked person's head in the 2D camera projection — frame 693
shows the near-approach, 695 shows them separated again. Confirmed directly: track 59 (this candidate)
fires its fence-crossing event at exactly frame 694 — the single worst instant for a clean silhouette —
while track 41 (the dark-jacketed person) fires its own crossing event one frame later at 695, once
clearly separated (that track's own confidence, 0.770, is unaffected by any synthetic transform). This
explains both why baseline daytime confidence was already only moderate (0.756 — a real detector
genuinely scores a partially-merged two-person silhouette lower even undistorted) and why this exact
frame is uniquely fragile to ANY further degradation, regardless of type: an already-ambiguous
silhouette has far less margin to absorb visual noise than a clean one does — unlike the 41 other real
crossings, most of which show a single, unambiguous person and are essentially unaffected by the same
mild haze. A complete, honest, rigorously-verified explanation for why this specific crossing became
the residual — not an unexplained coincidence — and a real confirmation that the Reliability Engine's
caution here tracks a genuine, measured confidence collapse.

## What specifically about the overlap confuses YOLO

Investigated one level deeper: not just "there is an occlusion," but the precise mechanism at the raw
model output. Re-running the real YOLOv8n model directly (not through the tracker) on frames 691-696 at
a low confidence threshold, to see every candidate box in the region:

| Frame | Tracked person (blue jacket) | Occluding person (dark jacket) |
|---|---|---|
| 691 | height 94px, conf 0.835 | height 84px, conf 0.729 |
| 692 | height 93px, conf 0.871 | height 80px, conf 0.783 |
| 693 | height 86px, conf 0.833 | height 77px, conf 0.611 (+ duplicate partial 52px box, 0.291) |
| **694** | height 99px, conf **0.756** | height **53px**, conf **0.436** |
| 695 | height 89px, conf 0.766 | height 83px, conf 0.770 (fully recovered) |

At the peak-overlap instant, the occluding person's own raw box truncates to roughly HALF its normal
height — his raised leg, mid-swing and overlapping the tracked person's head, is excluded from his own
box rather than included in it, producing an incompletely-proportioned shape the model scores far less
confidently (0.436, down from 0.611-0.783). The tracked person's own box, at the exact same frame,
grows slightly larger than usual (99px vs his typical 86-94px) — consistent with the intruding leg's
pixels being absorbed into the top of HIS box, distorting his silhouette away from a clean, canonical
person shape, plausibly explaining his own more modest confidence dip. Both boxes return to normal the
very next frame, once the silhouettes separate.

**The precise, measured answer:** it is not occlusion in the abstract, but a specific bounding-box
geometry disruption — one person's limb visually intruding into the other's silhouette region distorts
BOTH people's box proportions simultaneously, and YOLO's confidence scoring genuinely responds to that
distorted geometry, not just to "is a person present."

**Glare's residual was investigated too, and turned out to be a genuinely DIFFERENT situation from
fog/night — checked, not assumed.** Fog and night's classification rules structurally GUARANTEE every
classified frame fails the old reference (fog *requires* `contrast<30`, always below the old 60
"good" target; night *requires* `brightness<60`, always below the old 128 target — 100% of instances,
no exceptions). GLARE's classification (`glare_fraction > 0.15`) has no such ceiling: a frame right at
that boundary scores a reasonable `glare_score` of 0.5 under the current formula, not floored — only
frames at or past `glare_fraction ≥ 0.30` (double the classification minimum) floor to 0. This
specific synthetic transform's measured severity (~0.43) simply sits well past that point. That is a
transform-intensity limitation — the same honestly-disclosed category as fog/night's transform
intensity — not a formula defect calling for a seventh fix. No further change applied.

**That conclusion was then actually tested with a milder glare transform, the same way as fog's.**
`--synthetic-condition glare_mild` (×1.3+10, vs the original ×1.8+20) was empirically tuned against 5
frames spanning the whole video to measure `glare_fraction≈0.21` — still reliably `GLARE` (comfortably
above the real 0.15 cutoff throughout) but much closer to the boundary than the original's ~0.43. All
52 candidates again reviewed — zero false positives.

| Glare intensity | Genuine candidates | DETECTED | UNCERTAIN |
|---|---|---|---|
| Original (`glare_fraction≈0.43`) | 55 | 33 (60%) | 22 (40%) |
| Milder (`glare_fraction≈0.21`) | 52 | 46 (88%) | 6 (12%) |

An even larger confirmation than fog's: 60% → 88%. This makes sense given the ORIGINAL glare
transform's severity relative to its own threshold was proportionally much larger than fog's
(~2.9x the 0.15 cutoff, vs fog's transform, which was always below its 30 cutoff by construction, not
several multiples past it) — so there was correspondingly more room for a milder version to recover.
The 6 remaining `glare_mild` residuals show moderate, plausible `D`/`T` combinations (no floor, no
single dominant factor, `S`≈0.63-0.68 for all, `H`=1.0) — genuine evidence-based uncertainty, not a
further bug.

**The same paired daytime comparison used for `fog_mild`'s residual, applied to all 6 `glare_mild`
residuals, tells a real, more varied story than a single clean outlier.** Matching 47 of 52 candidates
to a daytime candidate at the same `frame_idx`:

| Residual | Matched drop (daytime D − glare_mild D) |
|---|---|
| Frame 694 (same crossing as `fog_mild`'s residual) | **0.309** |
| Next-largest drop (of the other 51) | 0.042 |
| candidate_011 (nearest-frame match, 1-frame offset) | ≈0.087 |
| Other 4 residuals | −0.032 to 0.001 (essentially none) |

Frame 694 is once again by far the largest drop — roughly 7x the next-largest — confirming this same
real person (at the peak-occlusion instant with a second, overlapping pedestrian identified in the
`fog_mild` finding) is uniquely fragile to visual degradation IN GENERAL, not just fog: the single
hardest real detection in this whole
dataset, across every condition tested. **But the other 5 residuals show essentially no real,
glare-specific confidence penalty** (two are even marginally negative). They are UNCERTAIN not because
glare degraded their detection confidence, but because their baseline daytime confidence was already
moderate (`D≈0.56-0.73` even in clear conditions) — `S`'s real, uniform glare penalty (a scene-quality
signal, not a per-candidate confidence hit) combined with real `T` factors is what tips these
already-borderline detections under threshold, not an outsized `D` collapse the way frame 694 shows. A
more complete picture than "no bug found" alone: one real outlier crossing is universally fragile; the
rest are ordinary borderline detections that glare's uniform scene-quality penalty tips over.

## A real compound condition: night AND fog together

Every condition above tests ONE degradation at a time, matching `SceneCondition`'s real design — a
single, mutually-exclusive categorical value (`edge/condition/scene_condition.py`). But a real border
camera can face darkness AND fog simultaneously. `--synthetic-condition night_fog`
(`scripts/collect_calibration_data.py`) combines the real night-darkening transform with a real
fog-style haze blend dimmed to match (not daytime fog's bright 190 — real fog under low light scatters
into a dim gray, it doesn't glow white), producing a genuinely compound degradation: `brightness_mean
≈39`, `contrast_std≈7` — lower contrast than EITHER "night" (≈15) or "fog" (≈21) alone. Because
`FOG_RAIN` requires `brightness>60`, this compound scene is always classified `LOW_LIGHT_NIGHT`, never
`FOG_RAIN` — a real, structural consequence of the categorical design, not a test artifact.

Two real findings from actually running it (all real candidates manually reviewed — zero false
positives, as always):

1. **This session's reliability-scoring fixes generalize correctly to a case more severe than either
   was individually measured against.** `_SCENE_CONTRAST_GOOD_NIGHT` (fix 4) still applies and
   correctly scores this worse than either individual condition; the H exemption
   (`_WEATHER_EXPLAINED_DEGRADED_REASONS`, fixes 1/6) still covers `LOW_LIGHT_NIGHT` if blur trips. Of
   the real candidates that reached a reliability decision, 5/7 DETECTED — the few survivors are
   handled reasonably. No new double-penalty or reference-point bug was found.
2. **A more fundamental finding: only 7 real fence-crossing candidates formed across all 795 frames,
   versus ~52 for every single-degradation condition — an ~86% drop in candidate YIELD, not detection
   accuracy.** At this severity, most real crossings never reach the Hybrid Reliability Engine at all
   — they are lost earlier, in detection/tracking itself. No amount of tuning
   `RELIABILITY_WEIGHT_*`/`RELIABILITY_R_THRESHOLD` addresses this, since those only ever see
   candidates that already survived to become one. **This is the honest, important distinction to
   report: the Reliability Engine's threshold accuracy on survivors is not the same claim as "the
   system reliably detects crossings under severe compound degradation."** This project has no fix for
   the latter — it would need detector-level work (a fine-tuned model, or preprocessing tuned to this
   specific compound case), outside this session's scope.

`n=7` is too small to treat the 71% DETECTED figure as a precise measurement — reported as an honest
observation on a small sample, not a statistically confident rate, unlike the ~52-candidate figures
elsewhere in this report.

## A second compound condition: night AND glare together

`--synthetic-condition night_glare` tests a different real compound scenario from `night_fog`: darken
the whole frame (real night), then add a real, LOCALIZED bright glow (empirically tuned to
`glare_fraction≈0.164`) — modeling a dark scene with a strong nearby light source (headlights, a
floodlight), not a uniformly bright one. Because GLARE's classification check runs FIRST in the real
decision order, this compound scene is classified `GLARE`, not `LOW_LIGHT_NIGHT` — the opposite
categorical outcome from `night_fog`. All 52 real candidates manually reviewed — zero false positives.

| Compound condition | Classified as | Candidates formed | DETECTED |
|---|---|---|---|
| `night_fog` (uniform low contrast everywhere) | `LOW_LIGHT_NIGHT` | 7 | 5/7 (71%) |
| `night_glare` (localized bright glow, dark elsewhere) | `GLARE` | 52 | 45/52 (87%) |

Two real, useful findings from the contrast between them:

1. **Unlike `night_fog`, candidate yield did not collapse.** 52 real candidates formed — the same
   order of magnitude as every single-degradation condition, not `night_fog`'s 7. A concentrated
   bright glow next to an otherwise dark scene does not crush detection/tracking the way UNIFORM low
   contrast across the whole frame does. The honest lesson: it is specifically *uniform* contrast
   collapse, not "any severe compound degradation," that threatens candidate yield.
2. **DETECTED (87%) is actually higher than the original single-condition "glare" transform's 60%**,
   because this compound scene's `glare_fraction` (≈0.164) sits in the same mild-severity regime as
   `glare_mild` (≈0.21) rather than the original severe transform (≈0.43) — confirming the earlier
   mild-intensity findings generalize here, not a new result on its own. The 7 remaining residuals
   show the same moderate `D`/`T` pattern as every other residual this session — genuine
   evidence-based uncertainty, no new bug.

## A third compound condition: all of night, fog, AND glare stacked together

`--synthetic-condition night_fog_glare` composes `night_fog`'s darken+haze-blend with `night_glare`'s
localized glow, plus a final blur — and surfaced a different, more severe, and honestly
self-inflicted finding: stacking two Gaussian blurs, a flat haze blend, and a fully static
(frame-invariant) glow overlay cumulatively suppresses real frame-to-frame pixel differences far more
than any pairwise combination did.

**Directly instrumented, not inferred:** over the first 260 frames, `CameraHealthMonitor`'s real
frame-differencing check (`variance = np.var(absdiff(prev, cur))`) measured `frozen_stream` on 250 of
them (96%) — genuinely below the real `FROZEN_FRAME_VARIANCE_THRESHOLD` (5.0) — correctly triggering
Gate 1's hard ABSTAIN override BEFORE detection even runs. Candidate yield collapsed to just **3**
(even lower than `night_fog`'s 7).

**This is an honest limitation of over-compounding synthetic degradations in a test script, not a
defect in `CameraHealthMonitor` or the Reliability Engine.** The health check is doing exactly what
it's designed to do — correctly detecting that this specific synthetic composition drowns out real
motion below what a real, working camera would ever produce. A real border camera under real
triple-degraded conditions would not have a perfectly static overlay baked into every single frame
the way this test's glow mask does.

**A secondary, smaller real observation:** `excessive_blur` fired on 10 of those 260 frames, and since
the classifier's real priority order makes this scene `GLARE` (not `FOG_RAIN`/`LOW_LIGHT_NIGHT`), the
existing blur exemption (fixes 1/6) does not cover it — `EXCESSIVE_BLUR` during `GLARE` still fully
penalizes `H`, even though the blur's real cause here is genuinely the co-occurring fog component, not
glare itself. **Left open, not force-fixed**: blindly adding `GLARE` to the blur exemption set would
incorrectly exempt a genuinely dirty/defocused lens during real glare with no fog involved — a real
structural consequence of a single categorical label only ever reporting one of several genuinely
co-occurring conditions, worth documenting honestly rather than papering over with a fix justified by
one small, synthetically-constructed case.

Of the 3 real candidates that survived Gate 1 at all, 1/3 DETECTED — `n=3` is too small to treat as
anything beyond an anecdotal observation, unlike every other figure in this report.

## A fourth compound condition: daytime fog with sun glare — tests the open blur question at real scale

`--synthetic-condition fog_glare` combines the same daytime fog blend as "fog" (bright haze 190) with
the same localized glow as `night_glare` — modeling a real, plausible scenario: driving/looking into
low sun on a foggy day. Checked before the real collection: `frozen_stream` fired on only 14/260 frames
(5%, healthy — one blur, not two, doesn't suppress variance the way `night_fog_glare`'s stacked blurs
did), but `excessive_blur` fired on **246/260 (95%)** — turning the earlier "left open, n=3" question
into a real, at-scale confirmation.

**The fix, real and unit-tested:** rather than add `GLARE` to the label-keyed blur exemption (which
would incorrectly also exempt a genuinely dirty lens during real glare with no fog — confirmed never
happening across ~160 real pure-glare candidates, all with contrast 55-94, well above 30),
`_health_quality_score` now also exempts `EXCESSIVE_BLUR` whenever the real measured `contrast_std` is
directly below `FOG_CONTRAST_THRESHOLD`, regardless of which label won the classification. 3 new tests;
full suite 242/242; every earlier dataset re-verified unchanged.

**Honestly, at first, re-measuring `fog_glare` with the whole-frame-scalar fix found it did NOT solve
the case it was built for:**

| | DETECTED |
|---|---|
| `fog_glare`, whole-frame-scalar fix, actual result | 0/52 (0%) |
| `fog_glare`, if the exemption HAD fired (`H=1.0` hypothetically) | 37/52 (71%) |

The reason: this scene's measured `contrast_std≈41` is ABOVE `FOG_CONTRAST_THRESHOLD` (30) — the
localized bright glow inflates the frame's GLOBAL contrast statistic well past what the hazy majority
of the frame shows on its own. A single global scalar cannot distinguish "uniformly hazy" from "hazy
background plus one small very-high-contrast bright spot." The 71% hypothetical confirmed the original
diagnosis was correct — this was a real, substantial problem, not a false alarm — but that first fix
wasn't sufficient to catch it.

## The region-aware contrast fix, actually implemented and verified

Rather than leave the region-aware measurement as documented future work, it was built.
`edge/condition/scene_condition.py::SceneConditionClassifier` now also computes
`contrast_std_excluding_glare` — spread among non-blown-out pixels only, reusing the same near-white
band `glare_fraction` already flags rather than a new cutoff. `SceneConditionReport` carries it as an
optional field (defaults to `None`, so any caller constructing a report directly — tests, fixtures —
is unaffected). `_health_quality_score`'s contrast-based exemption now uses this region-aware value,
falling back to whole-frame `contrast_std` when absent. Deliberately scoped: `_decide()` — what
actually gates `FOG_RAIN`/`GLARE` classification — still uses the original whole-frame `contrast_std`
exactly as before; only the exemption's own internal check changed. 9 new tests for the classifier
(`tests/unit/test_scene_condition.py`, this module's first-ever test file) plus 3 more for the
exemption using the new field; full suite 254/254; every earlier real dataset re-verified unaffected.

**Re-measured, real result:**

| | DETECTED |
|---|---|
| `fog_glare`, whole-frame-scalar fix | 0/52 (0%) |
| `fog_glare`, region-aware fix | **37/52 (71%)** |
| `fog_glare`, hypothetical prediction (last section) | 37/52 (71%) — matches exactly |

Confirmed via `contrast_std_excluding_glare≈22` (genuinely below 30, correctly reflecting the hazy
non-glow majority) and `H=1.0` across all 52 candidates. The small-sample `night_fog_glare` case
(`n=3`) also moved from 1/3 to 3/3 DETECTED — consistent, though still too small to be quantitatively
meaningful; Gate 1's `frozen_stream` override (a separate, previously-documented finding) still
dominates that dataset's low candidate yield, unaffected by this fix. This is now a real, complete,
verified fix for the fog+glare compound blur problem it targets — not future work.

## night_fog_glare's yield collapse, validated with a milder triple-compound intensity

The same milder-intensity validation applied to fog/night/glare's own residuals was applied to
`night_fog_glare`'s severe candidate-yield collapse. `--synthetic-condition night_fog_glare_mild` uses
`night_mild`'s lighter darkening (×0.45 vs ×0.28), a milder haze blend (70/0.65 vs 45/0.5), a smaller
glow blur kernel (15×15 vs 21×21) — and drops the extra whole-frame final blur entirely, the change
expected to matter most (stacking two Gaussian blurs plus a fully static glow overlay was the
diagnosed cause of the original frozen-frame collapse).

Checked before the real collection: frame-to-frame variance across the first 260 frames stayed above
`FROZEN_FRAME_VARIANCE_THRESHOLD` (5.0) on every single frame (min ≈7.3), versus 96% below threshold
for the original — confirming the frozen-frame collapse really was this specific transform's severity,
not an inherent property of any triple-compound scene. All 52 real candidates reviewed — zero false
positives.

| | Candidates formed | DETECTED |
|---|---|---|
| `night_fog_glare` (original intensity) | 3 | 1/3 (33%) |
| `night_fog_glare_mild` | 52 | 48/52 (92%) |

Candidate yield recovered to the same order of magnitude as every other dataset this session, and
DETECTED reached 92% with `H=1.0` across all candidates — confirming both the Gate-1 and blur-exemption
fixes generalize correctly to this milder triple-compound case too.

**The residual, investigated with the same rigor as standalone glare's, surfaced one genuine nuance.**
Sorting all 52 by `D` shows the boundary is mostly clean, but not purely `D`-driven this time:
`candidate_004` (`D=0.68` — higher than several DETECTED candidates) is still UNCERTAIN because it's a
genuinely very young track (`T_age_score=0.06`, only 4 trajectory points — the fence-crossing event
fired almost immediately after the track was created). The other 3 residuals show the same real,
moderate `D`+`T` combination pattern. All 4 visually re-confirmed as genuine, correctly-detected
people. `S`≈0.72 and `H`=1.0 for all four, so neither is the driver — unlike standalone `glare`'s
residual (`D` alone cleanly separated DETECTED/UNCERTAIN), this milder triple-compound residual is
jointly explained by `D` AND `T`: real evidence, correctly and conservatively weighed, not a bug in
either factor alone.

## UI fixes, cross-camera corroboration, a real external dataset, and a real production incident

A later pass covered five distinct pieces of work, summarized here for the report; the full
technical account of each is in `docs/ARCHITECTURE.md`'s changelog and `docs/LIMITATIONS.md`.

**1. UI bug sweep (all 7 dashboard pages checked).** Five real, fabricated/incorrect values found
and fixed — most notably the Architecture page, which stated things as fact that directly
contradicted this report: "TensorRT Optimized" (never true — plain CPU YOLOv8n, exactly as this
report's own Test run metadata says), a fixed "FPS 30.0 / RESOLUTION 4K UHD" (fabricated), a
reliability-gate description of "DETECTED ≥85% / UNCERTAIN 50-84% / ABSTAIN <50%" (not the real
gate — the real formula is `R = 0.40D+0.20T+0.20S+0.20H` banded at 0.75, ABSTAIN is Gate 1's
camera-health override), a hardcoded SHA-256 value that was specifically the well-known hash of
the *empty string*, and "Hyperledger Fabric consensus network" stated as fact when the real
runtime label is MOCK mode. Also fixed: a fake "PERSON #184 | 91% CONF" detection box shown on
every dashboard load before any real event occurred, a header CSS clipping bug (confirmed via the
rendered `<h1>`'s own bounding box, not a guess), unauthenticated polling spamming 401s forever,
and the Evidence page fabricating "DETECTION TYPE: Human" / "EDGE NODE: edge-001 (Active)" for
every event regardless of what was real.

**2. Cross-camera corroboration (poster §12B/§13) — first real implementation.** Confirmed by
grepping the whole repo that nothing implemented camera topology, ETA, or the temporal-consistency
formula `Tc = e^(-|Δt-t_expected|/σ)` before this. Built in `backend/services/cross_camera.py`:
real haversine distance from each camera's real admin-entered coordinates, a real expected-travel-
time range from a disclosed walking-speed heuristic, and the exact `Tc` formula. Explicitly
**not** person re-identification (no face/appearance matching exists anywhere in this codebase) —
disclosed everywhere as temporal+spatial plausibility only. Never rewrites an already-signed
event's decision — stored as separate columns instead, to protect the tamper-evident
chain-of-custody this report's own evidence pipeline depends on.

**3. A real external dataset (MOT16), and the first real calibration fit this project has ever
had.** Every calibration attempt in this report and in `docs/LIMITATIONS.md` was correctly
REFUSED because this report's own video (`demo/videos/vtest.avi`, per Test run metadata above) has
zero real false positives once reviewed — no negative examples anywhere to calibrate against.
MOT16 (Milan et al., CC BY-NC-SA 3.0, non-commercial research use) ships real, human-annotated
ground truth, so raw YOLO candidates could finally be checked against a real, independent answer
instead of a human review. Real result: MOT16-04 (marketplace) → 712 real false positives of 3834
candidates; MOT16-02 (street) → 1417 of 3268. Both produced a real, non-degenerate
`CalibrationModule.fit()` — MOT16-04 → threshold 0.410; MOT16-02 → threshold 0.100. **The honest
headline is that these two real numbers disagree** — reported as-is, not reconciled, and neither
is applied to this project's own runtime defaults (a threshold fitted on one real camera doesn't
obviously transfer to a camera neither sequence was even filmed on).

**4. Cross-camera corroboration wired into escalation, on explicit request.** A MEDIUM-severity
event with strong real corroboration (`Tc ≥ 0.6`) is now also escalation-eligible, alongside the
existing HIGH-severity condition. LOW is never boosted. The original, signed `Event.severity`
field is never mutated; every alert created this way is transparently marked
(`Alert.escalated_via_corroboration`), never a silent change in behavior.

**5. A real production incident, found and fixed.** The escalation change above shipped a DB
migration as `BOOLEAN DEFAULT 0` — passed the full local test suite (298/298) and crashed the live
Render deployment on startup, because Postgres enforces `BOOLEAN`'s real type and rejects an
integer literal default, while SQLite (all this project's local testing runs against) accepts it
silently. Found by directly polling the live deployment for ~15 minutes until it was clear the
build wasn't just slow, then reading the real Render deploy log. Fixed (`DEFAULT FALSE`), and a
regression test was added and *verified to actually catch the original bug* (reverted the fix,
watched the test fail, restored it) before being trusted. **This revealed a real, structural gap**:
this project's test suite runs against SQLite only — there is no Postgres available in this dev
environment — so any other SQLite-lenient/Postgres-strict divergence has the same blind spot. Not
fixed by more tests alone; disclosed as a standing limitation in `docs/LIMITATIONS.md`.

Verified end-to-end on the live deployment after the fix: `/health` → 200, `/system/verify-chain`
→ real chain integrity confirmed, `/events` schema carries the new corroboration fields, `/alerts`
and `/cameras` correctly 401 for unauthenticated requests, and all 7 dashboard pages render
correctly with no fabricated data. Full local suite: 302/302.

## Honesty checklist before this goes in the PPT

- [x] Every number above came from a JSON file this run actually produced (`docs/PERFORMANCE_REPORT_MEASURED.json`), not estimated
- [x] The machine/hardware is stated exactly, and no number is presented as if measured on different hardware
- [x] The false-positive-reduction claim is NOT asserted — the honest result (no measured reduction on this clip) is reported instead of a more convenient-sounding number
- [x] The video source is disclosed as a generic public test clip, not the team's actual demo footage — do not imply otherwise in the deck
- [x] Verified directly (not assumed) that no crossing in this report's real-data calibration work is an actual intrusion — every DETECTED/UNCERTAIN number measures reliability-scoring behavior on real object detections, not intrusion-detection accuracy — see "None of this report's real crossings are actual intrusions" above
- [x] The Architecture page's prior false claims (TensorRT, fabricated FPS/resolution, wrong reliability-gate bands, a fake SHA-256, "Hyperledger Fabric" stated as fact) are fixed and now match this report — do not let a stale screenshot of that page back into the deck
- [x] MOT16's two real fitted thresholds (0.410 vs 0.100) are reported as disagreeing, not averaged or cherry-picked into a single "the calibrated threshold" claim
- [x] The Postgres production incident is disclosed, including the structural gap it revealed (no Postgres available in this dev environment) — not glossed over as "found and fixed" alone
- [x] Re-run against real, denser footage (MOT16-04) — found a real 14.3% alert reduction from the
  Event Verifier, closing the "needs footage with real jitter" gap the original run flagged. Still
  **not** the team's own staged demo footage (doesn't exist, can't be fabricated — see
  `docs/LIMITATIONS.md`); state that distinction if this number goes in the PPT.

## Re-measurement (2026-09-07): the 44.6ms/21.8-FPS figure is stale for the full pipeline

**Context:** a fresh audit pass found and fixed two real crashes (`docs/ARCHITECTURE.md`'s "Real
Environment Audit" entry) and, separately, fixed face detection actually finding faces at all in
this environment (bundled a real cascade XML — see that entry too). Re-running
`scripts/run_false_positive_benchmark.py` afterward to check whether the original latency figure
still held surfaced a real, previously-undisclosed measurement gap, not a regression in the
underlying pipeline.

**The benchmark script itself reproduces the original numbers closely — nothing in what it
measures has regressed:**

| | frames | raw candidates | alerts | mean frame (ms) | FPS |
|---|---|---|---|---|---|
| Original (`PERFORMANCE_REPORT_MEASURED.json`) | 795 | 52 | 23 | 44.6 | 21.8 |
| Re-run, `required_confirmations=1` | 795 | 52 | 23 | 43.5 | 22.3 |
| Re-run, `required_confirmations=3` (shipped default) | 795 | 52 | 23 | 46.7 | 20.8 |

The false-positive result (52→23, identical under both confirmation policies) reproduced exactly.
Full JSON: `docs/PERFORMANCE_REPORT_REMEASURED_2026-09-07.json`.

**But `run_false_positive_benchmark.py` only ever wired up a SUBSET of what the real, deployed
`edge.main.EdgePipeline` runs per frame** — `CameraHealthMonitor`, `SceneConditionClassifier`,
`CalibrationModule`, `DetectionTracker`/YOLO, `VirtualFenceModule`, `make_reliability_decision`,
`EventVerifier`, `PipelineMetrics` (confirmed by reading the script directly, not assumed). It has
never included the `AdaptiveComputeGate`, `TrackContinuityGuard`, `TrackFeatureTracker`,
`LineCrossingModule`, `BehaviorModule`, `ANPRModule`, or `FaceDetectionModule` — all real, all
added to `edge/main.py` after this script (and the original benchmark) were written, and all run
on every relevant track, every frame, in the actual deployed pipeline.

**Measuring the real, full `EdgePipeline` directly** (`tests/integration/test_edge_pipeline_real_video_e2e.py`,
and a standalone timing script run before writing that test) on the same clip shows **~165-175ms
mean per frame (≈5.7-6 FPS) across the first 200 real frames — before any vehicle enters frame and
before ANPR's EasyOCR call ever fires** (which is slower again once it does, see
`docs/ARCHITECTURE.md`'s audit entry). The most likely real contributor, not fully isolated this
pass: face detection now genuinely runs real Haar-cascade inference on every person track inside
the verification zone every frame (previously it crashed the instant that happened — see the audit
entry — so it never actually ran to completion before now), on top of the Track Continuity Guard's
per-track histogram work, `BehaviorModule`'s dwell tracking, and `TrackFeatureTracker`'s trajectory
math, none of which the narrower benchmark script ever exercised.

**Honest conclusion: do not cite 44.6ms/21.8 FPS as the current full-pipeline number.** It remains
an accurate, reproducible measurement of the narrower detection+reliability+verifier stack the
benchmark script exercises, but it materially understates the real, currently-deployed
`EdgePipeline`'s actual per-frame cost. **Not done this pass** (real, disclosed follow-up work, not
silently deferred): extending `run_false_positive_benchmark.py` (or a new script) to wire up every
stage `edge/main.py` actually runs, so a single, honest, full-pipeline number can replace this
report's original figure everywhere it's cited.
