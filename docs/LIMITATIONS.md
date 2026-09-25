# NETRAKSH — Known Limitations

This file is the single source of truth for "is X actually real, or a placeholder" — referenced
from `docs/ARCHITECTURE.md`, `edge/detection/calibration.py`, and `edge/rules/modules.py`. If a
claim in the PPT or a demo script isn't backed by a line in this file (or isn't flatly true of the
code), don't make the claim. Update this file in the same change that closes or introduces a
limitation — an out-of-date limitations file is worse than none.

## 1. Fundamental limitations (not fixable by more engineering time alone)

- **Face detection currently finds zero faces on this dev machine, regardless of input.**
  `edge/rules/modules.py::FaceDetectionModule` tries RetinaFace first, Haar cascade second — both
  are currently non-functional in this environment. `retina-face` requires `tensorflow`, which has
  no published wheel for Python 3.14 (`pip install` fails with a dependency-resolution error); the
  Phase-0 environment-spike table at the top of `docs/ARCHITECTURE.md` marking `retina_face` as
  "⚠️ PARTIAL... installed" no longer reflects reality and should be re-verified, not trusted, before
  citing it. The Haar cascade fallback fails for a different, also environment-specific reason:
  this project's OpenCV build is `opencv-contrib-python-headless` (swapped from plain
  `opencv-python` for `cv2.face`/LBPH watchlist recognition), and that build's `cv2/data/` directory
  ships no `.xml` cascade files at all (confirmed by listing it directly). Before this audit pass,
  `_detect_haar()` called `detectMultiScale()` on the resulting empty classifier unconditionally,
  which raised a real `cv2.error` and **crashed the entire real-time edge frame loop** the moment a
  real person track entered a "verification"-type zone — confirmed directly against
  `demo/videos/vtest.avi` (crashed on frame 1). That crash is now fixed (`_detect_haar()` returns
  `None` instead of calling into an empty classifier — see `docs/ARCHITECTURE.md`'s "Real
  Environment Audit" entry), but face detection genuinely detects nothing until either dependency
  is restored (a working `tensorflow` wheel, or a cascade XML file added to the repo/certs and
  pointed at explicitly instead of `cv2.data.haarcascades`). Watchlist matching
  (`edge/detection/face_recognition.py`) is real and independently tested, but has no real face
  crops to run against in this environment as a direct consequence.
- **This project's entire test suite runs against SQLite only — there is no Postgres available in
  this dev environment — and this already caused one real production incident.** The
  `escalated_via_corroboration` DB migration (`backend/database/session.py`, added when wiring
  cross-camera corroboration into escalation) shipped as `BOOLEAN DEFAULT 0`, passed the full local
  suite (298/298), and crashed the live Render deployment on startup: Postgres enforces `BOOLEAN`'s
  real type and rejects an integer literal default (`psycopg2.errors.DatatypeMismatch`); SQLite has
  no real `BOOLEAN` type and accepts `0`/`1` silently, so nothing local could have caught it. Fixed
  (`DEFAULT FALSE`, valid in both) and a direct regression test added
  (`tests/unit/test_db_migration.py::TestMigrationSqlIsPostgresCompatible`, verified to actually
  fail against the original buggy line before trusting it) — but that test only catches this one
  specific pattern (an integer literal on a BOOLEAN column). Any other SQLite-lenient/Postgres-strict
  divergence in a future migration (or elsewhere) has the same structural blind spot: local
  testing, however thorough, cannot substitute for testing against the real production database
  engine, and this project cannot do that in its current dev environment. See
  `docs/ARCHITECTURE.md`'s "Real Production Incident" entry for the full account.
- **Detection model is COCO-pretrained YOLOv8n, not fine-tuned on a border-surveillance dataset.**
  Night, fog, rain, and unusual terrain/viewpoint accuracy is a *data* problem, not an architecture
  problem — no amount of pipeline engineering around it changes what the underlying detector was
  trained to recognize. `edge/condition/scene_condition.py`'s CLAHE preprocessing (once wired, see
  §3 below) and the calibration module's per-condition thresholds are mitigations, not fixes.
- **None of the "real fence crossings" in this entire session's extensive real-data calibration work
  (500+ candidates across daytime, night, fog, glare, and every compound/mild variant) represent an
  actual intrusion. This was checked directly, not assumed.** The zone tested throughout is documented
  (`docs/PERFORMANCE_REPORT.md`) as "visually placed over the main pedestrian walkway visible in the
  clip" — investigating this concretely using frame 694 (the most closely-examined candidate in this
  whole exercise) confirms exactly that: the frame's actual taped-off/coned restricted area (real white/
  red tape and cones, clearly visible) is a SEPARATE dirt/mulch patch elsewhere in frame — the drawn
  zone instead covers the open, paved plaza where multiple ordinary pedestrians casually cross in every
  direction simultaneously in the same single frame. The specific tracked person is a real, correctly-
  detected individual walking calmly and directly across an open public walkway — confirmed
  quantitatively, not just visually: real path smoothness `0.878` and speed consistency `0.746` over a
  sustained 38-point trajectory, with nothing erratic, evasive, or unusual about the movement. **This
  generalizes to the entire real-data calibration effort, not just this one candidate**: every "genuine
  crossing" (label=1) collected and manually reviewed this session is real in the sense that a real,
  correctly-detected person genuinely crossed the marked polygon boundary — but NONE represent trespass,
  forced entry, evasion, or any other genuine security-relevant intrusion pattern; they are all ordinary
  foot traffic through a normal campus walkway, chosen specifically because it reliably produces a high
  volume of real, benchmark-quality pedestrian crossings for calibration purposes. **What this session's
  real-data work honestly validates**: the Hybrid Reliability Engine's D/T/S/H scoring mechanics respond
  correctly to real image degradation, real double-penalties, and real edge cases (occlusion, blur,
  compound conditions) using genuine, non-fabricated object detections. **What it does NOT and cannot
  validate**: whether the system correctly flags genuine border/security intrusions, since no such
  scenario — staged or real — exists anywhere in the tested footage. This is consistent with, and gives
  a concrete, visually-confirmed example for, this project's own pre-existing disclosure elsewhere in
  this file that a real staged-intrusion dataset has never been used to validate this system.
- **Hybrid Reliability Engine weights and threshold are hand-picked, not calibrated — and a real
  attempt to calibrate them found this project's available real footage cannot supply what
  calibration needs.** `RELIABILITY_WEIGHT_D/T/S/H` and `RELIABILITY_R_THRESHOLD`
  (`edge/reliability/decision.py`) are shipped defaults chosen to preserve the qualitative behavior
  of the original 3-gate cascade on its own test cases. Architecture v4 §8's suggested upgrade path
  — fitting the weights via `LogisticRegression` over real labeled data — was actually attempted:
  `scripts/collect_calibration_data.py` ran the real production pipeline (real YOLOv8n detection,
  real `TrackFeatureTracker`, and the real `_scene_quality_score`/`_health_quality_score` functions
  imported directly from `edge/reliability/decision.py`, not reimplemented) against the same real
  video and zone already used for `docs/PERFORMANCE_REPORT.md`
  (`demo/videos/vtest.avi`, `(0.456,0.260)`–`(1.0,0.521)`), producing the same 52 real raw
  fence-crossing candidates that report already documents — each with its real `D`/`T`/`S`/`H`
  feature values and a labelable snapshot image (`scripts/calibration_data/`). A single reviewer then
  manually looked at every one of the 52 snapshots and labeled it by hand
  (`scripts/calibration_data/manifest.json`). The real, honest result: **all 52 are genuine detections
  of real people genuinely at or crossing the marked zone (label=1) — zero false positives.**
  `scripts/fit_reliability_weights.py` detects this single-class case explicitly and refuses to
  produce a fit, rather than printing meaningless coefficients from a dataset with no negative
  examples. This is a real, useful negative result, not a shortcut: it shows this project's one
  available real video (a generic public daytime pedestrian clip) is the wrong kind of dataset for
  this specific calibration — an actual false-positive-producing dataset (night/fog/glare footage,
  animals, wind-blown foliage, sensor noise) would be needed, and none of that currently exists as
  real footage anywhere in this project (see the "No custom border-surveillance dataset exists" item
  below). The current hand-picked defaults are therefore left in place, unchanged, pending such a
  dataset — not because they're proven correct, but because no real labeled data exists yet that
  could prove them wrong. The scene-quality (`S`) and health-quality (`H`) scoring functions remain
  hand-picked heuristics for the same reason.
  **Follow-up that found a real, more actionable problem than the fit itself:** the same collection
  script was re-run with `--synthetic-condition night` and `--synthetic-condition fog` — an honest,
  disclosed OpenCV brightness/contrast/haze transform applied to the same real footage (the people and
  motion are unchanged and real; only the lighting is synthetic — see the script's docstring). Both
  transforms genuinely triggered the real `SceneConditionClassifier` into `LOW_LIGHT_NIGHT`/`FOG_RAIN`
  on every frame (measured, not asserted), and manual review again found zero false positives — so the
  weight-fitting refusal above holds under degraded conditions too. But checking the CURRENT hand-picked
  weights against these genuine crossings (`scripts/analyze_reliability_under_conditions.py`) surfaced
  a real, severe, previously-unmeasured failure mode: **under the synthetic fog condition, 0 of 52
  genuine crossings cleared `RELIABILITY_R_THRESHOLD` — every single one was marked UNCERTAIN, not
  DETECTED.** Under synthetic night, 59% were missed. Diagnosis: a double penalty, not two independent
  ones — fog genuinely reduces contrast, which `S` already measures directly, and the same blur used to
  simulate fog haze also genuinely trips the Camera Health Monitor's Laplacian blur detector, which used
  to *also* halve `H` for the exact same real cause. **This has since been fixed**:
  `edge/reliability/decision.py::_health_quality_score` now scores `H` as healthy (1.0), not 0.5, when
  health is DEGRADED specifically for `EXCESSIVE_BLUR` *and* the scene is already independently
  classified `FOG_RAIN` or `LOW_LIGHT_NIGHT` — any other DEGRADED reason, or blur during `CLEAR_DAY`,
  still fully penalizes `H` exactly as before (locked in by
  `tests/unit/test_reliability.py::TestWeatherExplainedBlurDoesNotDoublePenalize`, 4 new tests, all
  passing; full suite 211/211). Re-measuring the same real labeled fog candidates against the fixed
  formula raised DETECTED from 0/52 (0%) to 37/52 (71%) — real, substantial, and honestly re-measured,
  not just claimed. Night's numbers are genuinely unchanged (21/51 both before and after) because the
  night transform never happened to trip `EXCESSIVE_BLUR` in this dataset.
  **Second follow-up fix, same real diagnosis pattern:** 71% still left 29% of genuine fog crossings
  UNCERTAIN, traced to `_scene_quality_score`'s `contrast_score` judging every FOG_RAIN frame against
  `_SCENE_CONTRAST_GOOD` (60.0) — a clear-day ideal a scene classified FOG_RAIN can never meet, since
  `contrast_std < FOG_CONTRAST_THRESHOLD` (30.0) is literally the real rule
  `edge/condition/scene_condition.py`'s `SceneConditionClassifier` already uses to call a scene foggy
  in the first place. The fix reuses that same, already-existing `FOG_CONTRAST_THRESHOLD` constant as
  FOG_RAIN's own contrast reference, instead of inventing a new number — a frame right at the real
  classification boundary now scores full contrast marks; one meaningfully foggier than that still
  scores proportionally lower, so this isn't a blanket free pass (locked in by
  `tests/unit/test_reliability.py::TestSceneQualityFogContrastReference`, 4 more new tests; full suite
  215/215). `LOW_LIGHT_NIGHT`/`CLEAR_DAY`/`GLARE` are untouched at this stage (confirmed unchanged:
  21/51 before and after this fix). Re-measured result: fog rose further, from 71% to 87% DETECTED
  (45/52).
  **Third follow-up fix, same real pattern, this time for night:** night's own real measured driver was
  the SAME kind of bug on the brightness side — `brightness_score` judged every `LOW_LIGHT_NIGHT` frame
  against the `CLEAR_DAY` midpoint ideal (128.0), which a scene classified night can never meet, since
  `brightness_mean < BRIGHTNESS_NIGHT_THRESHOLD` (60.0) is literally the real rule that classifies a
  scene as night in the first place. The fix reuses `BRIGHTNESS_NIGHT_THRESHOLD` exactly the way the
  fog fix reused `FOG_CONTRAST_THRESHOLD`: within the night band, more light is unambiguously better
  (not "distance from an ideal"), so a frame at the real classification boundary now scores full
  brightness marks, and a darker one still scores proportionally lower (locked in by
  `tests/unit/test_reliability.py::TestSceneQualityNightBrightnessReference`, 4 more new tests; full
  suite 219/219). `FOG_RAIN`/`CLEAR_DAY`/`GLARE` are untouched (confirmed: fog's rate is identical
  before and after, 45/52 both times). Re-measured result: night rose from 41% to 61% DETECTED (31/51).
  **Fourth follow-up fix, same remaining gap as flagged above, addressed anyway with honest
  disclosure of what kind of fix this is:** `contrast_score` was still judging night frames against the
  clear-day contrast ideal (60.0). Unlike the fog fix and the night brightness fix above — both of
  which reuse a real constant that's already part of `SceneConditionClassifier`'s actual classification
  rule — `LOW_LIGHT_NIGHT`'s classification rule checks brightness only, so there is no existing
  "this is the real rule that made it night" constant for contrast to reuse. `_SCENE_CONTRAST_GOOD_NIGHT`
  is therefore a genuinely NEW, hand-picked heuristic (half of `BRIGHTNESS_NIGHT_THRESHOLD` = 30.0) —
  not calibrated, not a reused classification boundary, and explicitly disclosed as such rather than
  oversold as equivalent to fixes 2/3. Its justification is a real, statable physical property, not a
  guess: `contrast_std` measures the spread of a non-negative pixel-value distribution, and one whose
  mean is capped below `BRIGHTNESS_NIGHT_THRESHOLD` cannot have much spread without clipping at zero —
  so a legitimately-dark-but-not-defective night frame's achievable contrast is bounded by its own
  brightness headroom, not the clear-day sensor's full range. This is exactly the same category of
  hand-picked default as the *original* `_SCENE_CONTRAST_GOOD`/`_SCENE_BRIGHTNESS_IDEAL`/
  `_SCENE_GLARE_BAD` constants (locked in by
  `tests/unit/test_reliability.py::TestSceneQualityNightContrastReference`, 4 more new tests, including
  a regression lock confirming `FOG_RAIN`'s own contrast reference is unaffected; full suite 223/223).
  Re-measured result: night rose further, from 61% to 76% DETECTED (39/51).
  **Fifth fix — a real, previously-shipped PRODUCTION bug, found while investigating why 3/52 DAYTIME
  crossings still missed threshold despite S≈0.92 and H=1.0 (no scene/health issue to blame):**
  `TrackFeatureTracker` (`edge/temporal/track_features.py`) only ever registered a track's
  `_first_seen` time inside `compute()` — and both `edge/main.py` (the real, deployed pipeline) and
  `scripts/collect_calibration_data.py` only ever call `compute()` from an EVENT-triggered branch (a
  fence-crossing handler, firing once per track at the crossing transition). That means
  `_first_seen[track_id]` got registered at the moment of a track's FIRST qualifying event, not its
  real first-observed frame — so `age_seconds` was always `0.0` on that one call, regardless of how
  long the track had genuinely already existed. Measured directly, not assumed: the 3 daytime
  candidates each had 34-50 real trajectory points (1.4-2 real seconds of prior tracking) yet
  `T_age_score` was exactly `0.0` for all three. The fix: a new `TrackFeatureTracker.observe()`
  method, called unconditionally for every active track every frame in both `edge/main.py` and the
  collection script — independent of whether any rule event fires that frame — so age is registered
  the moment a track is truly first seen. 4 new tests
  (`tests/unit/test_track_features.py::TestObserveFixesEventTriggeredAgeZeroing`); full suite
  227/227. This bug was condition-independent, so it improved ALL THREE datasets at once when
  re-measured: daytime rose from 49/52 (94%) to **52/52 (100%)** — the 3 residual daytime candidates
  are now fully resolved; night rose from 39/51 (76%) to 47/51 (92%); fog rose from 45/52 (87%) to
  49/52 (94%). This is the largest single fix of the whole session, since — unlike fixes 1-4, which
  only changed `edge/reliability/decision.py`'s scoring heuristics — this corrects a genuine defect
  in the real, deployed edge pipeline's temporal-scoring wiring itself.
  **All five fixes together still leave a real, honest remainder** — 6% of genuine fog crossings and
  8% of genuine night crossings under these specific synthetic intensities are still marked
  UNCERTAIN. Daytime, notably, is now at 100% — the remaining gap is entirely in the two synthetic
  degraded-condition datasets. See `docs/PERFORMANCE_REPORT.md`'s "Reliability Engine behavior under
  real night/fog conditions" section for the full numbers and all five fixes' before/after comparison.
  **The night residual was investigated specifically and, unlike fixes 1-5, found to have NO further
  identifiable formula bug** — an important, honest negative result in its own right, not a gap left
  unexamined. All 4 remaining UNCERTAIN night candidates are genuine, correctly-detected people (each
  snapshot manually re-checked); `S` is nearly flat across all 51 night candidates (0.6815-0.6961 —
  this synthetic darkening is uniform per-frame, so scene quality barely varies candidate to
  candidate), so `D` (raw detector confidence) is what actually separates them. Sorting all 51
  candidates by `D` shows a clean, monotonic boundary: the 4 lowest-`D` candidates (0.48-0.63, vs a
  0.78 mean across the full set) are *exactly* the 4 that miss threshold, with `R` increasing smoothly
  right through the 0.75 cutoff — no jump, no double-counted penalty, no wrong reference point. This
  is the Reliability Engine correctly expressing more caution on the objectively weakest evidence in
  the dataset, not a defect. Improving it further would require either the weight-fitting this whole
  exercise already found impossible (no real dataset with actual false positives exists to fit
  against — see above), or real night footage to check whether this synthetic transform's specific
  darkening intensity is even realistic for the confidence drop it produces in YOLO — neither of which
  this investigation can honestly manufacture. Left open, not force-fixed.
  **That last point was then actually tested with a milder night transform, the same way as fog's and
  glare's.** `--synthetic-condition night_mild` (scale ×0.45 vs the original ×0.28) was empirically
  tuned against 5 frames spanning the whole real video to measure `brightness_mean≈53` — still
  reliably classified `LOW_LIGHT_NIGHT` (a consistent ~7-point safety margin under 60 throughout) but
  much closer to the boundary than the original's ~33. All 52 real candidates again manually reviewed
  — zero false positives. Re-measured: DETECTED rose from 92% (47/51, original night intensity) to
  **96% (50/52)** — a smaller improvement than fog's (94%→98%) or glare's (60%→88%), consistent with
  night having already had more of its structural issue addressed by the two earlier reference-point
  fixes (fixes 3 and 4) before this test — less headroom was left for a milder transform to recover.
  The 2 remaining `night_mild` residuals (`D=0.47` and `D=0.49`, both far below the 0.78 mean, with
  `T`/`S`/`H` all near-max) are the same genuine low-confidence-detection pattern as every other
  residual this session.
  **The same paired daytime comparison used for `fog_mild`'s and `glare_mild`'s residuals was applied
  here too, and told a third, real, distinct story.** Matching 41 of 52 `night_mild` candidates to a
  daytime candidate at the same `frame_idx`: one residual is, again, frame 694 — the SAME real crossing
  flagged as the largest outlier under BOTH `fog_mild` (drop `0.386`) and `glare_mild` (drop `0.309`) —
  showing a real drop of `0.262` here too. **This is now the THIRD independent condition, using three
  genuinely different kinds of visual degradation (haze/blur, brightening/washout, darkening), in which
  this exact same real person is the single largest confidence drop in its dataset** — a strong,
  cross-validated conclusion that this one real crossing (the peak-occlusion instant with a second,
  overlapping pedestrian identified in the `fog_mild` investigation) is universally the hardest real
  detection in this whole dataset, independent of which degradation is applied. The second residual (`candidate_032`, no exact
  frame match — nearest daytime candidate is 1 frame off, at frame 487) shows a comparably large real
  drop too (`≈0.246`, daytime `D=0.719` → night_mild `D=0.472`) — a DIFFERENT real person, not
  previously flagged, but similarly night-sensitive. **Unlike `glare_mild` (where only 1 of 6 residuals
  showed a real, condition-specific confidence collapse, and the other 5 were ordinary moderate-
  confidence detections tipped by `S`'s uniform penalty), BOTH of `night_mild`'s residuals are
  genuinely, substantially night-degraded detections** (~0.25 drop each) — a real, honest difference in
  character between night's and glare's residual populations, not just a coincidence of small sample
  size.
  **The same paired comparison was extended to the compound-condition datasets, and caught a real
  methodological mistake before it was published — worth documenting alongside the actual findings.**
  Frame-`idx` matching between two datasets is a useful heuristic, but is NOT guaranteed to be the same
  real track: when several people cross near the zone at similar times, a different physical person can
  fire the fence-crossing event at the same `frame_idx` in two separately-run datasets. This was caught
  directly: `night_fog` and `fog_glare` both flag a candidate at frame 242 with a large apparent drop
  (`≈0.265` against daytime's own frame-242 candidate) — but visually comparing the snapshots shows
  daytime's frame-242 candidate is a DIFFERENT person (mid-zone, near the sign) than the small, distant
  figure `night_fog`/`fog_glare` actually flag (top-right corner) — `night_fog` and `fog_glare` genuinely
  agree with EACH OTHER (identical figure, identical position), just not with daytime's own frame-242
  candidate. That specific "0.265 drop" comparison is retracted as spurious; every other comparison
  reported in this document (including every frame-694 instance below) was individually visually
  re-verified — identical scene composition, identical bounding-box position, identical surrounding
  people — before being reported, precisely because this false match was found.
  **With that correction in place, frame 694 (the universally fragile crossing from the `fog_mild`/
  `glare_mild`/`night_mild` findings above) shows up again, genuinely, in the compound datasets**:
  `fog_glare`'s candidate_042 (`daytime D=0.756` → `fog_glare D=0.491`, drop `0.265`) is visually
  confirmed as the same real crossing, and is again that dataset's single largest drop among its 15
  residuals — a FIFTH independent confirmation (daytime-paired) of this one crossing's universal
  fragility, now spanning every single-condition and several compound-condition transforms tested this
  session. `night_glare`'s 7 residuals, by contrast, show only small real drops (visually confirmed
  genuine for `candidate_026`, frame 345: `0.087`) — one is even marginally negative (`-0.035`) — none
  approaching frame 694's magnitude, consistent with `night_glare`'s already-healthy 87% DETECTED rate
  and its residuals being ordinary borderline detections, the same character as most of `glare_mild`'s
  residuals. `fog_glare`'s other 14 residuals mostly show small-to-moderate real drops (`0.003`-`0.106`)
  — a mix of ordinary borderline detections and mild, real fog-driven degradation, with frame 694 as the
  one standout. `night_fog_glare` has zero residuals (all 3 real candidates DETECTED) — nothing to
  investigate. `night_fog_glare_mild`'s residuals were already investigated in detail above (frame 694
  present again, plus a genuinely young-track case) — consistent with this same overall picture.
  **The fog residual was investigated the same way and reaches the identical honest conclusion.** All
  3 remaining UNCERTAIN fog candidates are genuine, correctly-detected people (each snapshot manually
  re-checked — small/distant figures visibly softened by the haze/blur transform). `S` is nearly flat
  across all 52 fog candidates (0.8126-0.8295), so again `D` is what separates them: sorting all 52 by
  `D` shows the same clean, monotonic boundary — the 3 lowest-`D` candidates (0.52-0.56, vs a 0.76
  mean across the full set) are *exactly* the 3 that miss threshold, `R` increasing smoothly right
  through 0.75. Same conclusion as night: this is the Reliability Engine correctly expressing more
  caution on the objectively weakest evidence, not a defect, and left open for the same reason (no
  real dataset to fit against, no real fog footage to validate the transform's intensity).
  **This "no bug, just transform severity" conclusion was then actually tested, not just assumed.**
  A second, deliberately MILDER fog transform (`--synthetic-condition fog_mild`: blend 0.55/0.45 with
  a smaller 5x5 blur, vs the original 0.42/0.58 with 7x7) was empirically tuned against 5 frames
  spanning the whole real video to measure `contrast_std≈28` — still reliably classified `FOG_RAIN`
  (a consistent ~2-point safety margin under the real 30 threshold throughout), but right at the
  boundary rather than deep inside it. All 52 real candidates again manually reviewed — zero false
  positives. Re-measured: DETECTED rose from 94% (49/52, the original fog intensity) to **98% (51/52)**
  — a real, honest confirmation that milder fog genuinely produces fewer misses, validating that at
  least part of the original 6% residual was a transform-severity effect, not pure irreducible
  evidence-based caution. The single remaining `fog_mild` residual (`D=0.37`, far below the 0.77 mean,
  with `S=0.92`/`H=1.0`/`T=0.85` all near-max) is the same genuine, low-confidence-detection pattern
  already established for every other residual this session — visually confirmed as a real person,
  no bug.
  **This residual was then compared directly against the unmodified daytime footage of the exact same
  real moment — a real, paired before/after measurement, not just "D happens to be low."**
  `demo/videos/vtest.avi` frame 694 has a real, matched candidate in BOTH the daytime (`D=0.756`) and
  `fog_mild` (`D=0.369`) datasets — visually confirmed as the same real person, same real crossing
  (identical scene layout and bounding-box position in both snapshots). Systematically matching all 52
  `fog_mild` candidates to a daytime candidate at the exact same `frame_idx` (42 of 52 matched) found
  this is by far the LARGEST confidence drop in the dataset (`0.386`) — roughly 10x the next-largest
  (`0.035`) — while the other 41 matched candidates cluster tightly near a mean drop of just `0.005`.
  **`fog_mild`'s real effect on detection confidence is not a uniform mild degradation across all real
  crossings — it is heavily concentrated in this one outlier.** An initial visual pass suggested a
  similar-colored background (a pile of tree branches/mulch behind the person) as the explanation — but
  a real, rigorous investigation (re-extracting the exact bounding box from the drawn snapshot, pulling
  the raw frame directly from the video, and inspecting the surrounding frame sequence 691-696) found
  the ACTUAL cause, and it's more precise and more interesting: **frame 694 is the peak instant of a
  real, transient partial occlusion between two real pedestrians.** A second, taller person (dark
  jacket) is walking almost directly behind/past the tracked person (blue jacket) — visible in the
  sequence, his raised leg swings up and, at exactly frame 694, visually touches/overlaps the tracked
  person's head in the 2D camera projection (frame 693: near-approach; frame 694: peak overlap; frame
  695: separated again). Confirmed directly: track 59 (blue jacket, this candidate) fires its
  fence-crossing event at exactly frame 694 — the single worst instant for a clean, unambiguous
  silhouette — while track 41 (dark jacket) fires its OWN crossing event one frame later at 695, once
  clearly separated (that track's confidence, `0.770`, is unaffected by any of the synthetic
  transforms). This is a real, physical explanation for why baseline daytime confidence was already
  only moderate (`0.756`, not near-perfect — a real detector genuinely finds a partially-merged
  two-person silhouette harder to score confidently even undistorted) and why the SAME frame is
  uniquely fragile to ANY further degradation, regardless of type (fog, night, glare, and combinations
  all independently flag it): an already-ambiguous, borderline silhouette has far less margin to
  absorb further visual noise than a clean, single-person silhouette does — unlike the 41 other real
  crossings, most of which show a single, unambiguous person and are essentially unaffected by the same
  mild degradation. This is a complete, honest, rigorously-verified explanation for why THIS specific
  real crossing became the residual, not an unexplained coincidence — and a useful, real confirmation
  that
  the Reliability Engine's caution here tracks a genuine, measured, real-world confidence collapse.
  **Investigated further: what SPECIFICALLY about the overlap confuses YOLO, at the level of the raw
  model output, not just "there is an occlusion."** Re-running the real YOLOv8n model directly (not
  through the tracker) on the raw frame sequence 691-696, at a low confidence threshold to see every
  candidate box in the region, gives a precise, quantified mechanism:

  | Frame | Tracked person (blue jacket) box | Occluding person (dark jacket) box |
  |---|---|---|
  | 691 | height 94px, conf 0.835 | height 84px, conf 0.729 |
  | 692 | height 93px, conf 0.871 | height 80px, conf 0.783 |
  | 693 | height 86px, conf 0.833 | height 77px, conf 0.611 (+ a duplicate, partial 52px box at 0.291) |
  | **694** | height 99px, conf **0.756** | height **53px**, conf **0.436** |
  | 695 | height 89px, conf 0.766 | height 83px, conf 0.770 (fully recovered) |

  At the peak-overlap instant, the occluding person's OWN raw YOLO box truncates to roughly HALF its
  normal height (`53px` vs `77-84px` in adjacent frames) — his raised leg, mid-swing and overlapping the
  tracked person's head, is excluded from his own bounding box rather than included in it, producing an
  incompletely-proportioned "person" shape that the model itself scores far less confidently (`0.436`,
  down from `0.611-0.783`). The tracked person's own box, at the exact same frame, GROWS slightly larger
  than usual (`99px` vs his own typical `86-94px`) — consistent with the intruding leg's pixels being
  absorbed into the top of HIS box instead, distorting his silhouette's proportions away from a clean,
  canonical person shape, which plausibly explains his own more modest confidence dip (`0.833→0.756`).
  Both boxes return to their normal height and confidence the very next frame, once the two people's
  silhouettes separate. This is the precise, measured answer: it is not occlusion in the abstract, but
  a specific, real bounding-box geometry disruption — one person's limb visually intruding into the
  other's silhouette region distorts BOTH people's box proportions simultaneously, and YOLO's
  objectness/confidence scoring genuinely responds to that distorted geometry, not just to "is a person
  present."
  **Sixth fix — GLARE, the fourth and last real `SceneCondition`, tested the same way.** A synthetic
  glare transform was added to `scripts/collect_calibration_data.py`
  (`--synthetic-condition glare`: scale pixel values ×1.8+20 and clip at 255, empirically measured
  against this video's own first frame to reliably classify `GLARE` via the real `glare_fraction`
  path — ~0.43, well past the real 0.15 cutoff — rather than the `brightness>220` path). All 795
  frames genuinely classified `GLARE`; manual review of all 55 real candidates again found zero false
  positives. The SAME real double-penalty pattern as fog was found here too: glare genuinely blows
  out highlights, which `S` already penalizes via `glare_fraction`, **and** the same real
  overexposure genuinely trips the Camera Health Monitor's OWN, unrelated exposure-clipping check
  (`clip_fraction` — fraction of pixels at exactly 255 — measured at 30-41% here, far past its 0.10
  threshold) into `ABNORMAL_EXPOSURE`, which used to *also* halve `H` for the same real cause,
  producing an initial, honestly-measured 0/55 (0%) DETECTED — identical to fog's original result.
  The fix generalizes fix 1's exemption from a single hardcoded case into a real
  `_WEATHER_EXPLAINED_DEGRADED_REASONS` mapping (`edge/reliability/decision.py`) — `{EXCESSIVE_BLUR:
  {FOG_RAIN, LOW_LIGHT_NIGHT}, ABNORMAL_EXPOSURE: {GLARE}}` — so a third such pairing, if ever found,
  is a one-line addition, not new code (4 new tests,
  `tests/unit/test_reliability.py::TestWeatherExplainedExposureDoesNotDoublePenalize`; full suite
  239/239). Re-measured: glare rose from 0/55 (0%) to **33/55 (60%) DETECTED**.
  **Unlike fog/night, the remaining 40% was investigated and found to be a genuinely different
  situation, not the same class of reference-point bug** — checked before assuming one existed, not
  after: fog and night's classification rules structurally GUARANTEE every classified frame fails the
  old reference (fog *requires* contrast<30; night *requires* brightness<60, both below their old
  60/128 "good" targets, for 100% of instances, no exceptions). GLARE's classification
  (`glare_fraction > 0.15`) has no such ceiling — a frame right at that boundary scores a reasonable
  `glare_score` of 0.5 under the CURRENT formula, not floored; only frames at or past
  `glare_fraction ≥ 0.30` (double the classification minimum) floor to 0. This specific synthetic
  transform's measured severity (~0.43) simply sits well past that point — a transform-intensity
  limitation, the same honestly-disclosed category as fog/night's transform intensity, not a formula
  defect to fix. No further change applied.
  **This "transform severity, not a bug" conclusion was then actually tested, the same way as fog's**
  (see `docs/PERFORMANCE_REPORT.md`'s milder-fog result above): a second, deliberately milder glare
  transform (`--synthetic-condition glare_mild`: ×1.3+10, vs the original ×1.8+20) was empirically
  tuned against 5 frames spanning the whole real video to measure `glare_fraction≈0.21` — still
  reliably classified `GLARE` (comfortably above the real 0.15 cutoff throughout) but much closer to
  the boundary than the original's ~0.43. All 52 real candidates again manually reviewed — zero false
  positives. Re-measured: DETECTED rose from 60% (33/55, original glare intensity) to **88% (46/52)**
  — an even larger confirmation than fog's, since the original glare transform was proportionally
  far more severe relative to its own classification threshold (~2.9x vs fog's transform, which was
  always below its threshold by construction). The 6 remaining `glare_mild` residuals show moderate,
  plausible `D`/`T` combinations (no floor, no single dominant factor, `S`≈0.63-0.68 for all,
  `H`=1.0) — genuine evidence-based uncertainty, not a further bug.
  **The same paired daytime comparison used for `fog_mild`'s residual was applied to all 6 `glare_mild`
  residuals, and told a real, more varied story than a single clean outlier.** Matching all 52
  `glare_mild` candidates to a daytime candidate at the same `frame_idx` (47 of 52 matched) found the
  SAME real crossing (frame 694) is once again by far the largest confidence drop (`0.309`) — roughly
  7x the next-largest (`0.042`) — confirming this specific real person (at the peak-occlusion instant
  with a second, overlapping pedestrian identified in the `fog_mild` investigation) is uniquely
  fragile to visual degradation IN GENERAL, not just fog specifically: it is the single hardest real
  detection in this whole dataset across every condition tested. **But the other 5 residuals tell a
  genuinely different, honest story — matched drops of `-0.002`, `-0.003`, `-0.032`, `0.001`, and
  (nearest-frame, 1-frame offset) `≈0.087` — essentially NO real, glare-specific confidence penalty**
  (two are even marginally negative, i.e. `glare_mild`'s `D` was fractionally HIGHER than daytime's for
  the same crossing). These 5 residuals are UNCERTAIN not because glare degraded their detection
  confidence, but because their baseline daytime confidence was already moderate (`D≈0.56-0.73` even in
  clear conditions) — `S`'s real, condition-driven glare penalty (uniform across all `glare_mild`
  candidates, not a per-candidate confidence hit) combined with real `T` factors is what pushes these
  specific already-borderline detections under threshold, not an outsized glare-specific `D` collapse
  the way frame 694 shows. A more complete, more honest picture than "no bug found" alone: one real
  outlier crossing is universally fragile; the rest are ordinary borderline detections that glare's
  real, uniform scene-quality penalty (not a confidence attack on that specific detection) tips over.
- **`SceneCondition` is a single, mutually-exclusive categorical value — a real scene that is genuinely
  BOTH foggy AND dark cannot be represented as such, only as one or the other, and this was tested, not
  just noted as a theoretical gap.** A new `--synthetic-condition night_fog`
  (`scripts/collect_calibration_data.py`) combines the real night-darkening transform with a real
  fog-style haze blend on top of it (dimmed to match, not daytime fog's bright 190 — real fog under
  low light scatters little into a dim gray, it doesn't glow white), producing a real compound
  degradation: `brightness_mean≈39`, `contrast_std≈7` — genuinely lower contrast than EITHER "night"
  (≈15) or "fog" (≈21) alone. Because `FOG_RAIN`'s classification rule requires `brightness>60`
  (`edge/condition/scene_condition.py`), this compound scene is always classified `LOW_LIGHT_NIGHT`,
  never `FOG_RAIN` — a real, structural consequence of Gate 2's categorical design, not a bug in this
  test. Two real findings came out of actually running it:
  1. **The reliability-scoring fixes already made this session generalize correctly to a MORE severe
     case than either was individually measured against** — no new double-penalty or reference-point
     bug was found. `_SCENE_CONTRAST_GOOD_NIGHT` (fix 4) still applies, correctly scoring this more
     severe contrast worse than either individual condition; `_WEATHER_EXPLAINED_DEGRADED_REASONS`
     (fixes 1/6) still applies if blur trips (`LOW_LIGHT_NIGHT` was already in its exemption set).
     Manual review of all real candidates found zero false positives, and of those, 5/7 (71%)
     DETECTED — the few candidates that survive to a reliability decision are handled reasonably.
  2. **A more fundamental, more operationally significant real finding: only 7 real fence-crossing
     candidates ever formed across all 795 frames, versus ~52 for every single-degradation condition
     tested this session — an ~86% drop in candidate YIELD, not just detection accuracy.** At this
     severity, the overwhelming majority of real crossings never even reach the Hybrid Reliability
     Engine at all — they are lost earlier, in detection/tracking itself (YOLO confidence and/or
     ByteTrack continuity degrading under compounded low-contrast, low-light pixels), a limitation no
     amount of tuning `RELIABILITY_WEIGHT_*`/`RELIABILITY_R_THRESHOLD` can address, since those only
     ever see candidates that already survived to become one. This is real, honest, and important to
     say plainly: the Reliability Engine's threshold accuracy on survivors is not the same claim as
     "the system reliably detects crossings under severe compound degradation," and this project has
     no fix for the latter yet — it would require detector-level work (a fine-tuned model, adaptive
     preprocessing tuned to this compound case specifically) outside this session's scope. `n=7` is
     also too small to treat the 71% DETECTED figure itself as a precise measurement — it is reported
     as an honest observation on this small a sample, not a statistically confident rate.
  **A second real compound condition — night AND glare together — was tested too, and the contrast
  with `night_fog` above is itself an honest, useful finding.** `--synthetic-condition night_glare`
  darkens the whole frame the same way "night" does, then adds a real, LOCALIZED bright glow (a
  blurred filled circle, empirically tuned against 5 frames spanning the whole video to drive
  `glare_fraction≈0.164` — comfortably past the real 0.15 cutoff) — modeling a real scenario a border
  camera can face: a dark scene with a strong nearby light source (oncoming headlights, a floodlight,
  lens flare), not a uniformly bright one. Because GLARE's classification check runs FIRST in the real
  decision order (`edge/condition/scene_condition.py::_decide()`), this compound scene is classified
  `GLARE`, not `LOW_LIGHT_NIGHT` — the opposite categorical outcome from `night_fog`'s compound scene,
  which always fell to `LOW_LIGHT_NIGHT` since `FOG_RAIN` requires `brightness>60`. All 52 real
  candidates manually reviewed — zero false positives, as always. Two real findings:
  1. **Unlike `night_fog`, candidate YIELD did not collapse — 52 real fence-crossing candidates
     formed, the same order of magnitude as every single-degradation condition, not `night_fog`'s 7.**
     A concentrated bright glow next to an otherwise dark scene does not crush detection/tracking the
     way UNIFORM low contrast across the whole frame does — if anything, the glow's sharp edges may
     even help. This is a genuine, useful contrast between two compound scenarios that both sound
     "severe" in isolation.
  2. **DETECTED rose to 87% (45/52)** — actually higher than the original single-condition "glare"
     transform's 60%, because this compound scene's `glare_fraction` (≈0.164) is much closer to the
     real classification boundary than the original glare transform's (≈0.43), putting it in the same
     mild-severity regime as `glare_mild` rather than the original severe one — this is expected,
     confirming the fog/night/glare mild-intensity findings above generalize here too, not a new
     result on its own. The 7 remaining residuals show the same moderate `D`/`T` pattern (no floor, no
     single dominant factor, `S`≈0.666-0.667, `H`=1.0 for all) as every other residual this session —
     genuine evidence-based uncertainty, no new bug.
  **A third compound condition — all of night, fog, AND glare stacked together
  (`--synthetic-condition night_fog_glare`) — surfaced a real, different, more severe finding than
  either compound above, and it is honestly a limitation of the SYNTHETIC TRANSFORM's own
  composition, not the pipeline.** Composing `night_fog`'s darken+haze-blend with `night_glare`'s
  localized glow, then a final blur, produced a real, measured side effect: stacking two separate
  Gaussian blurs, a flat haze blend, AND a fully static (frame-invariant) glow overlay cumulatively
  suppresses real frame-to-frame pixel differences far more than any pairwise combination did.
  Directly instrumented (not inferred): over the first 260 frames, `CameraHealthMonitor`'s real
  frame-differencing check (`edge/health/camera_health.py`, `variance = np.var(absdiff(prev, cur))`)
  measured `frozen_stream` on 250 of them (96%) — genuinely below the real
  `FROZEN_FRAME_VARIANCE_THRESHOLD` (5.0) — correctly triggering Gate 1's hard ABSTAIN override
  BEFORE detection even runs. This is why candidate yield collapsed to just **3** (even lower than
  `night_fog`'s 7): the health check is doing exactly what it is designed to do, correctly detecting
  that this specific synthetic composition drowns out real motion below what a real, working camera
  would ever produce. This is an honest limitation of over-compounding synthetic degradations in a
  test script, not a defect in `CameraHealthMonitor` or the Reliability Engine — a real border camera
  under real triple-degraded conditions would not have a perfectly static overlay baked into every
  frame the way this test's glow mask does.
  A secondary, smaller real observation from the same instrumentation: `excessive_blur` fired on 10 of
  those 260 frames, and — since the classifier's real priority order makes this scene `GLARE` (not
  `FOG_RAIN`/`LOW_LIGHT_NIGHT`) — the existing blur exemption (`_WEATHER_EXPLAINED_DEGRADED_REASONS`,
  fixes 1/6) does NOT cover it, so `EXCESSIVE_BLUR` during `GLARE` still fully penalizes `H`, even
  though in this specific compound scene the blur's real cause is genuinely the co-occurring fog
  component, not glare itself. This is a real, structural consequence of a single categorical label
  only ever reporting ONE of several genuinely co-occurring conditions — but it is NOT fixed here:
  blindly adding `GLARE` to the blur exemption set would incorrectly exempt a genuinely dirty/defocused
  lens during real glare with no fog involved, which has nothing to do with this specific compound
  scenario. Left open as a documented, real limitation of the categorical design, not force-fixed on
  the strength of one small, synthetically-constructed case.
  Of the 3 real candidates that survived Gate 1 at all, 1/3 DETECTED — `n=3` is far too small to treat
  as anything beyond an anecdotal observation, unlike every other figure in this document.
  **A fourth compound condition — daytime fog with sun glare (no night darkening) — was used to test
  the "left open" blur/co-occurring-condition gap above at REAL SCALE (n=52, not the n=3 anecdote
  above), and turned an open question into a concrete, tested fix — which then honestly turned out to
  be real but incomplete.** `--synthetic-condition fog_glare` combines the SAME daytime fog blend as
  "fog" (bright haze 190, not `night_fog`'s dimmed 45) with the SAME localized glow as `night_glare`,
  modeling a real, plausible scenario (driving/looking into low sun on a foggy day). Checked BEFORE
  the real collection, learning directly from `night_fog_glare`'s side effect: direct instrumentation
  of 260 real frames found `frozen_stream` on only 14 (5%, healthy — one blur, not two, plus a static
  glow does not suppress frame-to-frame variance the way stacking two blurs did) — but `excessive_blur`
  fired on 246 (95%), confirming the open question at real scale, not anecdote: this scene's real,
  genuine blur (from the same fog transform's blur, present regardless of the glow) is not exempted,
  because the winning classification is `GLARE`, and `EXCESSIVE_BLUR`'s exemption only covered
  `FOG_RAIN`/`LOW_LIGHT_NIGHT`.
  **The fix, real and unit-tested:** rather than add `GLARE` to the label-keyed exemption (which would
  incorrectly also exempt a genuinely dirty/defocused lens during real glare with no fog — confirmed
  never happening: `EXCESSIVE_BLUR` never fired once across ~160 real candidates from the pure
  `glare`/`glare_mild`/`night_glare` datasets, all of which had real contrast 55-94, well above 30),
  `_health_quality_score` now also exempts `EXCESSIVE_BLUR` whenever the REAL measured `contrast_std`
  is directly below `FOG_CONTRAST_THRESHOLD` — the same real constant, checked against the real signal
  instead of relying solely on which label won. 3 new tests
  (`tests/unit/test_reliability.py::TestWeatherExplainedBlurByRealContrastNotJustLabel`); full suite
  242/242; all five earlier real datasets (daytime/night/fog/glare/`night_glare`) re-verified byte-for-
  byte unchanged by this generalization.
  **Honestly, at first, re-measuring `fog_glare` with the whole-frame-scalar fix in place found it did
  NOT solve the real case it was built for: DETECTED stayed at 0/52 (0%), unchanged.** The real reason:
  this scene's measured `contrast_std` is `≈41` — ABOVE `FOG_CONTRAST_THRESHOLD` (30), because the
  localized bright glow inflates the FRAME'S GLOBAL contrast statistic well past what the hazy
  majority of the frame would show on its own (compare `night_fog_glare`, where the glow against a
  genuinely DARK background inflated global contrast even more, to ≈81). A single global scalar cannot
  distinguish "uniformly hazy" from "hazy background plus one small very-high-contrast bright spot."
  Recomputing what DETECTED would have been *if* the exemption had correctly fired (`H=1.0` for all 52)
  confirmed the diagnosis was still right: **37/52 (71%)** — the same order of magnitude as the
  original fog fix — showing this was a real, substantial problem, not a false alarm; the fix as first
  built simply wasn't sufficient to catch it.
  **The region-aware fix this pointed to was then actually implemented, not left as a future-work
  note.** `edge/condition/scene_condition.py::SceneConditionClassifier` now also computes
  `contrast_std_excluding_glare` — spread among non-blown-out pixels only (the same near-white band
  `glare_fraction` already flags, reused rather than a new cutoff), added to `SceneConditionReport` as
  an optional field (defaults to `None`, so every existing caller/test that constructs a report
  directly is unaffected). `_health_quality_score`'s contrast-based exemption now uses this
  region-aware value (falling back to whole-frame `contrast_std` when the field is absent), so a small
  bright region no longer masks genuine haze in the rest of the frame. Deliberately scoped: `_decide()`
  — what actually gates `FOG_RAIN`/`GLARE` classification — still uses the original whole-frame
  `contrast_std` exactly as before; only the exemption's OWN internal check changed. 9 new tests for
  the classifier (`tests/unit/test_scene_condition.py`, this module's first-ever test file — baseline
  regression coverage for `_decide()` plus the new region-aware measurement) and 3 new tests for the
  exemption using it (`tests/unit/test_reliability.py::TestWeatherExplainedBlurUsesRegionAwareContrast`);
  full suite 254/254. Every earlier real dataset re-verified unaffected.
  **Re-measured, real result: `fog_glare` rose from 0/52 (0%) to 37/52 (71%) DETECTED — matching the
  hypothetical prediction from the whole-frame-scalar attempt exactly**, confirmed via
  `contrast_std_excluding_glare≈22` (genuinely below 30, correctly reflecting the hazy non-glow
  majority) and `H=1.0` across all 52 candidates. The small-sample `night_fog_glare` case (`n=3`) also
  moved from 1/3 to 3/3 — consistent, though still too small to be quantitatively meaningful; Gate 1's
  `frozen_stream` override (a real, separate, previously-documented finding) still dominates that
  dataset's low candidate yield, unaffected by this fix. This is now a real, complete, verified fix —
  not "future work" — for the specific fog+glare compound blur problem it targets.
  **The `night_fog_glare` yield collapse itself was then tested with a milder triple-compound
  intensity, the same way fog/night/glare's own residuals were validated with `_mild` variants.**
  `--synthetic-condition night_fog_glare_mild` uses `night_mild`'s lighter darkening (×0.45 vs ×0.28),
  a milder haze blend toward a brighter gray (70 vs 45, blend 0.65/0.35 vs 0.5/0.5), a smaller glow
  blur kernel (15×15 vs 21×21) — and, the change expected to matter most, DROPS the extra whole-frame
  final blur entirely (the original's stacking of two Gaussian blurs plus a fully static glow overlay
  was the diagnosed cause of the frozen-frame collapse). Checked before the real collection: frame-to-
  frame variance across the first 260 frames stayed above the real `FROZEN_FRAME_VARIANCE_THRESHOLD`
  (5.0) on EVERY frame (min ≈7.3), versus 96% below threshold for the original — confirming the
  frozen-frame collapse really was this specific transform's severity, not an inherent property of any
  triple-compound scene. All 52 real candidates manually reviewed — zero false positives, as always.
  **Real result: candidate yield recovered from 3 to 52** (the same order of magnitude as every
  single/pairwise-condition dataset this session), and **DETECTED reached 92% (48/52)** — `H=1.0`
  across all candidates (the region-aware contrast fix correctly firing, `contrast_std_excluding_glare
  ≈18-19`, genuinely below `FOG_CONTRAST_THRESHOLD`), confirming both the Gate-1 and blur-exemption
  fixes generalize correctly to this milder triple-compound case too.
  **This residual — the classified `GLARE` case for a milder triple compound — was investigated with
  the same rigor as the standalone glare residual, and surfaced one genuine, honest nuance the
  standalone case didn't have.** Sorting all 52 by `D` shows the boundary is *mostly* clean (as it was
  for standalone `glare`), but not purely `D`-driven this time: `candidate_004` (`D=0.68` — higher than
  several DETECTED candidates) is still UNCERTAIN, because it is a genuinely very young track
  (`T_age_score=0.06`, only 4 trajectory points — the fence-crossing event fired almost immediately
  after the track was first created). The other 3 residuals (`candidate_026`, `032`, `042`) show the
  same real, moderate `D`+`T` combination pattern (short or mildly inconsistent tracks). All 4 visually
  re-confirmed as genuine, correctly-detected people — no anomaly. `S`≈0.72 and `H`=1.0 for all four,
  so neither is the driver here — unlike standalone `glare`'s residual, where `D` alone cleanly
  separated DETECTED from UNCERTAIN, this milder triple-compound residual is jointly explained by `D`
  AND `T`: real evidence, correctly and conservatively weighed by the formula, not a bug in either
  factor considered alone.
- **Temporal Evidence Intelligence (Mode A) implements 3 of the 5 originally-specified features.**
  `edge/temporal/track_features.py` computes track age, path smoothness, and speed consistency.
  Dwell-time-in-zone and revisit-count (the other two features named in architecture v4 §7) are not
  yet integrated into `T` — they exist as separate, zone-scoped bookkeeping inside
  `edge/rules/modules.py::BehaviorModule` today, not exposed to the Reliability Engine. Mode B (a
  `LogisticRegression` over labeled data) is not implemented — see `docs/ADR-TEMPORAL.md`.
- **Detection thresholds are prototype values, not calibrated from labeled data — and a real attempt
  was made, reusing the SAME real labeled data as the Reliability Engine's weight-calibration
  attempt above, which found the same fundamental limit AND a real bug in `fit()` itself.**
  `scripts/fit_detection_thresholds.py` fed `CalibrationModule.fit()` the already-reviewed,
  already-labeled fence-crossing candidates from all three real datasets
  (`scripts/calibration_data{,_night,_fog}/manifest.json`), bucketed by their real scene condition —
  the first real caller this module has ever had. As already established above, every one of these
  real candidates is a genuine detection (label=1) in every condition — zero false positives — so
  there is no real precision/recall signal anywhere in this project's footage to fit a threshold
  against, for the same underlying reason the weight-calibration attempt was refused.
  **A real, previously-latent bug was found in `fit()` while attempting this**: unlike
  `scripts/fit_reliability_weights.py` (built with an explicit single-class guard from the start),
  `CalibrationModule.fit()` had NO such guard — fed a single-class `labels` array, isotonic
  regression collapses to a constant ~1.0 regardless of confidence, every threshold in the F1 search
  then scores a meaningless perfect F1=1.0 (no negatives ever exist to produce a false positive), and
  the loop silently returns its very first candidate (0.1) as if it were a real, "calibrated"
  threshold — actively worse than the honest prototype default it would have replaced, and
  `is_calibrated()` would have reported `True`. This has been fixed: `fit()` now raises a `ValueError`
  and leaves the existing thresholds/`is_calibrated()` state completely unchanged when given
  single-class labels (8 new tests in the module's first-ever test file,
  `tests/unit/test_calibration.py`, including a regression check that the original, real isotonic/
  Platt logic still works correctly on genuine two-class synthetic data; full suite 235/235). The
  thresholds currently in force (`THRESHOLD_CLEAR_DAY` etc.) remain hand-picked, conservative
  defaults, explicitly logged as such at runtime. **Do not present these as calibrated in the PPT** —
  `fit()` has now actually been run, for real, against real labeled data, and correctly refused for
  all three conditions; that refusal is the honest, current status, not an untried gap anymore.
  **Update — a real dataset with real false positives has since been found (see the MOT16 entry
  below), and `fit()` now DOES produce a real, non-degenerate result against it.** It is still not
  applied to the runtime `THRESHOLD_*` defaults, for reasons explained there.
- **`fit()` finally has real negative examples to calibrate against — from MOT16, not this
  project's own footage — and the two real sequences tried disagree with each other.**
  `scripts/collect_mot16_ground_truth_calibration.py` (new) runs the real YOLOv8n detector at a
  low confidence floor (0.05) against real MOT16 CCTV frames and labels each raw candidate against
  real, human-annotated ground truth (IoU ≥ 0.5 with a real GT pedestrian box → real detection;
  IoU < 0.1 with every real GT box → real, GT-verified false positive; anything in between is
  genuinely ambiguous and excluded, never guessed). Unlike this project's own footage, MOT16
  actually has real false positives: MOT16-04 (1050 frames, marketplace) produced 712 real false
  positives out of 3834 candidates; MOT16-02 (600 frames, street) produced 1417 out of 3268.
  `scripts/fit_detection_thresholds_mot16.py` fed both through `CalibrationModule.fit()` and got a
  real, non-degenerate isotonic fit both times — **but the two real fitted thresholds disagree:
  0.410 for MOT16-04, 0.100 for MOT16-02.** That disagreement is itself an honest, useful finding,
  not a bug to paper over: a confidence threshold fitted on one real camera/crowd-density doesn't
  obviously transfer to a different one, which is exactly why this project does NOT apply either
  fitted value to `edge/detection/calibration.py`'s runtime `THRESHOLD_*` defaults automatically —
  doing so would mean picking one of two genuinely conflicting real answers and asserting it as
  "the" calibrated threshold for a camera neither sequence was even filmed on. Both are documented
  here as real results with a real caveat, not silently reconciled. MOT16 is Milan et al., "MOT16:
  A Benchmark for Multi-Object Tracking" (arXiv:1603.00831, https://motchallenge.net), CC
  BY-NC-SA 3.0, used here for non-commercial research (this SIH hackathon prototype) — the raw
  dataset (1.95GB) and per-candidate snapshot crops are NOT committed to this repo (gitignored,
  same as this project's own `calibration_data_*/snapshots/`); only `manifest.json` (numeric
  candidate data — confidence, bbox, IoU, label — no image bytes) is.
- **No custom border-surveillance dataset exists — real footage from other public benchmarks
  (MOT16, above) has been used to test calibration methodology, but no footage of this project's
  own actual border/checkpoint camera exists.** A future dataset covering night/fog/rain/terrain
  from the team's real deployment hardware could be collected and used to fine-tune the detector —
  this is documented as future work, not claimed as already done anywhere in this codebase.
- **Hardware target is intentionally generic, not a named board.** Per architecture v4 §2, no
  specific hardware (Jetson or otherwise) is claimed because the team has not benchmarked on one.
  Every FPS/latency number in `docs/PERFORMANCE_REPORT.md` is only valid for the machine it was
  actually measured on — see that file's metadata section.
  **Update — that number is now also stale relative to the pipeline's current feature set, not
  just the machine it ran on.** `docs/PERFORMANCE_REPORT.md`'s 44.6ms-mean/21.8-FPS figure predates
  several features added later in this project (ANPR, the Track Continuity Guard, Track Feature
  Tracker, real face detection/recognition, vehicle classification) that all run inside the same
  per-frame loop. Measured directly while building `tests/integration/test_edge_pipeline_real_video_e2e.py`:
  the first 200 real frames of `demo/videos/vtest.avi` (no vehicles yet visible) run at a steady
  ~175ms/frame — already ~4x the original figure — and a full-clip run was observed taking several
  times longer still once real vehicles enter frame and ANPR's EasyOCR call (CPU-heavy) starts
  firing. **Update — the benchmark script was re-run afterward, confirming this precisely**: it
  still reproduces the original 44.6ms/21.8-FPS figure almost exactly (43.5-46.7ms, 52→23
  unchanged under both confirmation policies) because it only ever wires up a subset of the real
  pipeline — it has never included `AdaptiveComputeGate`, `TrackContinuityGuard`,
  `TrackFeatureTracker`, `LineCrossingModule`, `BehaviorModule`, `ANPRModule`, or
  `FaceDetectionModule`. See `docs/PERFORMANCE_REPORT.md`'s "Re-measurement (2026-09-07)" entry for
  the full comparison table and honest conclusion: do not cite 44.6ms/21.8 FPS as the current
  full-pipeline number anywhere. Extending the benchmark script itself to cover every real stage
  remains real, disclosed future work, not done this pass.
- **AES-256 evidence encryption key is stored on the edge device's local disk**
  (`certs/edge/<camera_id>.aes`), not in a TPM/HSM. It protects evidence at rest from casual disk
  access or exfiltration of the storage medium, but **not** from an attacker who has already
  compromised the edge device itself. Hardware-backed key storage is future work.
- **`demo/scripts/zones_config.json`'s four zones are grounded in real footage (`demo/videos/vtest.avi`)
  but are still NOT the team's actual demo camera.** They were placed by visually inspecting real
  frames and matching each zone to something actually visible (a taped restricted area, a real
  pedestrian chokepoint, the only vehicle-parking area in frame, a signpost pause-point) — confirmed
  live by running the real benchmark against the fence zone (36 real candidate crossings fired) — not
  hand-picked round numbers with no visual basis, which is what they were before. This is a genuine
  improvement, but `scripts/define_zone.py` itself was never run interactively: that requires a live
  GUI window and real mouse clicks from a human operator, which isn't something that can be driven
  from here. Run it for real against your actual camera or video before a live demo — see
  `docs/ARCHITECTURE.md`'s changelog entry for exact usage.
- **A real, pre-existing `edge/data/sync.db` in this repository has an 8,578-deep never-synced queue**
  from an actual prior run (`edge/data/clips/` holds real JPEGs dated 2026-09-01). This suggests sync
  to a backend never actually succeeded during that run — worth checking directly (is a backend
  running? reachable? was `SIMULATE_OFFLINE` left on?) rather than assuming the store-and-forward path
  has been exercised end-to-end against a live server just because the code is tested.
- **Evidence captured before the AES-256 encryption change is not retroactively encrypted.** The real
  JPEGs in `edge/data/clips/` from that same prior run are plain, unencrypted files, because they
  predate `EvidenceEncryptor` (`edge/evidence/packager.py`) existing at all. Only evidence captured
  after that change is encrypted at rest. If demoing tamper-evidence or at-rest encryption specifically,
  use a freshly-generated event, not one of these historical files.
- **CLAHE's parameters and the night-motion fallback's cooldown are hand-picked, not calibrated.**
  `clipLimit=2.0` and `tileGridSize=(8,8)` (`edge/condition/preprocessing.py`) are the commonly-cited
  starting point for CLAHE on natural images, not values tuned against this project's own night/fog
  footage. `NIGHT_MOTION_COOLDOWN_SECONDS=30.0` (`shared/constants.py`) is similarly a starting guess
  at a reasonable debounce window. CLAHE is explicitly a mitigation for the detector's existing
  COCO-trained weights, not a fix for the underlying training-data gap (see the first bullet in this
  section) — it improves local contrast; it does not add information the sensor didn't capture.
- **Adaptive Compute Gate's thresholds are hand-picked, not calibrated.**
  `MOTION_GATE_VARIANCE_THRESHOLD` (15.0) and `IDLE_INFERENCE_INTERVAL_FRAMES` (5) in
  `shared/constants.py` are starting points chosen for plausibility relative to the existing frozen-
  frame threshold (5.0), not fit against real footage of an actually-idle border scene. A threshold
  set too low risks treating genuine slow motion as idle and briefly delaying detection; set too high,
  it saves little compute. This has not been measured on real footage — `docs/PERFORMANCE_REPORT.md`'s
  skip-ratio field, once populated from a real run, is exactly the number that would validate or
  correct this choice.
- **Track Continuity Guard's thresholds are hand-picked, not calibrated.** The border-tuned
  `track_buffer: 120` (`edge/config/bytetrack_border.yaml`), the histogram-similarity threshold
  (0.7), and the max centroid distance (150px) in `edge/tracking/continuity_guard.py` are starting
  points chosen for plausibility, not fit against real occlusion footage. Ultralytics' own comment on
  `track_buffer` is an honest tradeoff to repeat here: a higher value handles occlusion better but
  increases the risk of two different objects being wrongly merged into one identity. This has not
  been measured on real footage.
- **The one real false-positive measurement so far used a generic public test video, not the team's
  own footage, and found no measurable effect from temporal verification.** `docs/
  PERFORMANCE_REPORT.md` records this precisely: on `demo/videos/vtest.avi` (OpenCV's own sample
  clip), 23 of 52 raw fence-crossing candidates became alerts under *both* the 1-confirmation and the
  shipped 3-confirmation policy — the Event Verifier cost nothing but also proved nothing on this
  clip, because it contained no single-frame tracking jitter for it to catch. The Hybrid Reliability
  Engine's own filtering (52→23) is real and measured; the Event Verifier's specific benefit is not
  demonstrated by this run and needs footage with actual tracking instability to measure honestly. Do
  not claim a false-positive reduction number from temporal verification without re-running this
  against footage that actually exercises it.
- **That same run's CPU% reading (0.0) is not credible and must not be quoted.** A single end-of-run
  `psutil` sample doesn't capture sustained usage from a CPU-bound YOLO inference workload the way a
  periodic sampler would — `docs/PERFORMANCE_REPORT.md` flags this explicitly rather than reporting it
  as a real "0% CPU" result. The RSS memory reading (~410–430MB) from the same run is plausible and is
  reported normally.

## 2. Implemented, but scoped narrower than it might sound

- **Real external C2 (command-and-control) integration exists (SIH PS 26187), scoped honestly.**
  `backend/services/webhook_delivery.py` delivers a real, documented JSON payload
  (`WebhookAlertPayload`) to admin-registered outbound webhooks whenever a real `Alert` is created,
  plus a real pull-based `GET /integrations/events/export` for external systems that don't accept
  inbound webhooks. **Not** a named external standard (CAP, STIX/TAXII, etc.) — this project has not
  implemented or verified compliance against any such standard; the payload is a real, deliberately
  simple, project-specific JSON shape. **No retry queue** on a failed delivery — a subscription's
  own `last_delivery_status`/`last_delivery_error` fields are the real, honest signal something
  needs manual attention, not silently retried or silently dropped. **No delivery authentication**
  (HMAC signing, mTLS) — the receiving system is trusted to be reachable at whatever URL an admin
  registered; real, disclosed future work, not claimed as done.
- **This project has no Tailwind compiler — only a small hand-written CSS subset
  (`frontend/src/index.css`) — and several class names that look like Tailwind utilities
  throughout the frontend do nothing at all**, because they were never defined in that
  file. Confirmed (not assumed) via `getComputedStyle`: `.grid`, every `grid-cols-*`, and
  every responsive breakpoint prefix (`md:`, `lg:`, `xl:` — there are no `@media` rules in
  this file at all) silently collapsed every such layout to a single column. Found while
  building the real geospatial map (`docs/ARCHITECTURE.md`'s "Real Geospatial Map" entry)
  and fixed everywhere an exhaustive grep found it: `Alerts.jsx`, `Health.jsx` (twice),
  `Evidence.jsx`, `Dashboard.jsx` (twice), `Performance.jsx` — 7 total, all now real CSS
  Grid via inline `style`. The identical root cause as the earlier `text-center` bug
  (`Sidebar.jsx`, see the "Sidebar Logo Label Overflow Fix" entry). **Update — this WAS
  eventually investigated systematically, and the answer was far worse than "maybe a few
  more":** every `className` string used anywhere in the app was audited against what's
  actually defined in `index.css`. Over 100 classes were in real, active use — `.absolute`,
  `.relative`, `flex-grow`, `flex-1`, `flex-shrink-0`, `overflow-hidden`, `overflow-y-auto`,
  every `top-*`/`left-*`/`right-*`/`bottom-*` offset, every `mt-*`/`mb-*`/`pt-*`/`pb-*`/
  `px-*`/`py-*` spacing value, `z-10`/`z-20`/`z-50`, `text-center`, `uppercase`, `truncate`,
  `shadow-lg`, several `hover:*`/`disabled:*`/`last:*` pseudo-class variants, and more — with
  **no matching CSS rule anywhere**. `.absolute`/`.relative` alone affected 54 occurrences
  across 9+8 files. Found the same way as before: `getComputedStyle()` on a real, reported UI
  bug (the header's Sync Status dropdown rendering overlapping the header instead of below
  it) showed `position: static` where the `className` said `absolute`. Fixed with a
  comprehensive real utility layer in `index.css` matching Tailwind's actual semantics (same
  0.25rem-per-unit scale this file's own `.gap-*` classes already used), plus 12 remaining
  bracket/arbitrary-value classes (which a flat rule can't cover) converted to real inline
  styles, same pattern as the `grid`/`grid-cols-*` fix above. One real regression surfaced and
  fixed in the same pass: `VideoFeed`'s container collapsed to 1.6px tall once `.absolute`
  started working and stopped accidentally masking `min-h-[400px]`'s own identical bug — see
  `docs/ARCHITECTURE.md`'s "The Real Root Cause" entry for the full account, including what's
  still honestly unconverted (a handful of purely cosmetic `text-[10px]`/hover-tint classes,
  layout-safe, deliberately deprioritized). Treat any layout that looks visually "off" as
  worth checking this way — `getComputedStyle`, not eyeballing a screenshot — before assuming
  it's a different bug; screenshots alone missed this for the entire session until now.
- **The header's Sync Status panel now honestly calls the real `GET /system/verify-chain`
  for its "Chain Integrity" line** (previously a hardcoded "Chain Integrity OK" regardless
  of any real state) — this means it shows "N block(s) failed integrity verification. Chain
  compromised." in red for any event whose `EvidencePackage` doesn't carry a real,
  verifiable Ed25519 signature. `scripts/seed_demo_events.py` generates a real keypair per
  demo camera and signs every event properly. The live Render deployment's demo events are
  all real-signed as of this writing (`GET /system/verify-chain` reports
  `"Successfully verified 6 blocks across all edge hash chains."`) — an earlier batch of 8
  unsigned demo events was found, identified precisely by `event_id`, and removed directly
  from the live database (with the user's own credentials, in FK-safe order:
  `alerts` → `evidence_packages` → `events`) once discovered.
- **Every backend-generated timestamp is stored and returned as a naive datetime with no
  UTC marker** (`SQLAlchemy`'s `DateTime` columns, populated via `datetime.utcnow()`
  throughout the codebase — the same call this project's own test suite already flags as
  deprecated Python). This was fixed at the frontend (`frontend/src/utils/time.js`'s
  `parseUtc()`), not at the source: every `DateTime` column would need to become
  `DateTime(timezone=True)` for the backend itself to emit correctly-marked timestamps,
  which is a real schema migration across every timestamped table, not a one-line fix. The
  frontend fix is complete and verified for every timestamp this app currently displays,
  but any *new* timestamp display added later must remember to route through `parseUtc()` —
  the underlying naive-storage gap has not been closed, only worked around at its one
  actual point of failure (parsing in the browser). See `docs/ARCHITECTURE.md`'s "Real Data
  on the Live Deployment + a Timezone Bug Found While Seeding It" for how this was found.
- **ANPR is a simplified, non-production heuristic**, not a real license-plate detector. It crops a
  fixed lower-middle-third region of the *vehicle* bounding box (a rough heuristic for typical plate
  location) and runs EasyOCR directly on that crop — there is no dedicated plate-detection model
  ahead of OCR. This is fragile at odd angles, occluded plates, or non-standard vehicle proportions.
  It is scoped to checkpoint-angle cameras only (`ZoneType.CHECKPOINT`) and is intentionally kept out
  of the primary demo narrative — mention it only if directly asked, and describe it exactly this
  honestly.
- **Update — real watchlist facial recognition now exists (SIH PS 26187), with a deliberately
  narrow, honestly-disclosed scope.** `edge/detection/face_recognition.py` wraps
  `cv2.face.LBPHFaceRecognizer` (classical Local Binary Patterns Histograms — CPU-friendly, matching
  this project's stated posture throughout; requires `opencv-contrib-python-headless`, swapped in
  for the plain `opencv-python-headless` package, which never ships `cv2.face`). **Not** ArcFace or
  any deep-learning embedding-based recognizer — `dlib`/`face_recognition` has no reliable prebuilt
  wheel for this project's Python 3.14 environment, a real practical constraint, not just a
  preference. Real, meaningfully lower accuracy than modern recognizers, especially across
  lighting/pose/expression variation. **No liveness detection anywhere in this pipeline** — a
  printed photo held up to a camera matches exactly like the real person; never use a match as the
  sole basis for a consequential decision. Not appropriate for large-scale (hundreds+) 1:N
  identification — LBPH's real accuracy degrades as the enrolled population grows. Every match is a
  real algorithm output against real, admin-enrolled reference photos (`backend/api/watchlist.py`)
  — never fabricated — but treat every match as a lead for human review, never a confirmed
  identification on its own. See `docs/ARCHITECTURE.md`'s "Real Facial Recognition and External C2
  Integration" entry for the full technical account.
- **Blockchain is MOCK mode.** `MockBlockchainAdapter` is the active adapter because WSL2/Docker are
  unavailable on the development machine, so Hyperledger Fabric's `test-network` cannot run. The
  `FabricCLIAdapter` class implements the identical interface and is a one-line config swap
  (`BLOCKCHAIN_MODE=fabric`) away from being live, but it has never actually been exercised against a
  real Fabric network. On-chain scope is intentionally narrow either way — only `AlertIssued` /
  `AlertAcknowledged` transactions, never raw video or continuous health data.
- **RBAC has 3 roles (ADMIN/OPERATOR/AUDITOR)** with no granular per-zone or per-camera permission
  model. A richer Authorization & Context module (person/vehicle database, zone/time permissions) is
  explicitly Phase 2 per the architecture roadmap, not an MVP gap.
- **Clock drift detection is opportunistic**, comparing the edge device's system clock to frame
  timestamps — there is no hard NTP dependency or verification that the system clock itself is
  accurate, only that it is internally consistent with the frame stream.
- **`GET /events/{event_id}/evidence-image` only works because the backend and edge process share a
  filesystem in this project's current single-machine deployment.** `Event.evidence_clip_ref` has
  always been a local file path string, not the image bytes — `edge/sync/sync_client.py` never
  transmits the actual snapshot during sync, only this path. A real distributed deployment (edge and
  backend on different machines) would need the edge to upload the evidence bytes themselves during
  sync — a separate, larger change, not implemented.
- **The evidence-key KEK is derived from `settings.SECRET_KEY`, an application secret, not a
  dedicated secrets manager or HSM.** Anyone who has `SECRET_KEY` (already sensitive — it also signs
  every JWT) can derive the KEK (`backend/security/evidence_key_wrap.py`) and unwrap every camera's
  evidence key. HKDF with a domain-separation label at least prevents that derivation from also
  compromising anything else `SECRET_KEY` is used for, but this is a proportionate MVP tradeoff, not
  production-grade key management.
- **~~`GET /events/{event_id}` had no auth dependency at all~~ — FIXED.** As part of the pre-deployment
  hardening pass, both `GET /events/{event_id}` and `POST /events/{event_id}/verify`
  (`backend/api/events.py`) now require `require_any_role`, matching `GET /events/{id}/evidence-image`.
  Fixing this also surfaced two independent, unrelated frontend bugs in `Evidence.jsx`'s "Verify
  Netraksh Integrity Chain" button, both now fixed too: (1) it called the endpoint with a bare
  `fetch()`, which defaults to `GET` — the real route is `POST`, so this button had been silently
  405'ing (caught by the `catch` block) on every click since it was written; (2) even on a successful
  call it read a `data.is_valid` field that doesn't exist on `VerificationResponse` (the real fields are
  `hash_valid`/`signature_valid`/`chain_valid`), so it would have always reported "failed" regardless of
  the actual verification result. `list_events` (`GET /events`) still has no auth dependency — left as
  an open gap below, since making the dashboard's own live event feed require auth is a larger,
  deliberate call for the team, not a drive-by fix.
- **`GET /events` (`list_events`) still has no auth dependency.** Unlike the three endpoints above, this
  one is left open deliberately: the dashboard's live WebSocket feed and REST fallback both depend on
  reading events without a login gate today, and closing it means deciding whether unauthenticated
  viewers should see live event data at all — a product decision, not a one-line fix.
- **The frontend's `/health` SPA route (Camera Health Matrix) was renamed to `/camera-health`** — it
  collided with the backend's `GET /health` liveness probe (`backend/api/system.py`), which a real
  hosting platform (Render, Railway, Fly.io, etc.) will poll at that exact path for container health
  checks. Hitting `/health` directly (not via in-app client-side navigation) returned the backend's raw
  JSON instead of the page, since FastAPI's own route wins over the SPA catch-all. The backend's
  `/health` endpoint itself is untouched — it's the conventional liveness-check path and should stay
  there.
- **Every hardcoded `http://localhost:8443` / `ws://localhost:8443` string in the frontend (10 call
  sites) was replaced with a runtime-derived `BACKEND_URL`/`WS_URL` (`frontend/src/services/auth.js`,
  from `window.location`).** They worked only by coincidence, since the backend has always served the
  built frontend from that exact origin — deploying to any real domain would have silently broken
  every fetch and the live WebSocket. No config needed going forward; it resolves correctly under any
  origin automatically.
- **The "Demo Scenario Control" panel's four buttons (`frontend/src/components/DemoSidebar.jsx`) call
  backend routes that do not exist** — `/demo/inject-condition`, `/demo/trigger-camera-failure`,
  `/demo/simulate-offline`. Confirmed by grepping the entire backend; there is no `demo` router at all.
  Every click always falls through to the local-only "Simulated" UI state. This was already disclosed
  honestly in the UI (each button carries a "Simulated" badge) — not a hidden gap — but is recorded
  here explicitly now that it's been confirmed rather than merely flagged as unchecked. Implementing
  real scenario injection (forcing a camera's health/scene-condition state server-side for a live demo)
  is a real, if modest, feature — not attempted here.
- **`Header.jsx`'s periodic `GET /sync/status` poll (every 5s) requires `require_any_role`
  (`backend/api/system.py`) but nothing in the header ever prompts for login** — it 401s for the
  duration of any session that never visits the Evidence page's login form (which is the only place a
  viewer can sign in). Switched the call to `authFetch()` so it succeeds once a viewer is logged in,
  but the underlying design question — should sync status require auth at all, given the rest of the
  dashboard is viewable without logging in? — is left open, same category as `GET /events` below.
- **Pre-live-deployment checklist, not yet actioned (all require an explicit decision, not a drive-by
  fix):**
  - `SECRET_KEY` (`backend/config.py`) defaults to the literal string `"CHANGE_ME_USE_openssl_rand_hex_32"`
    when not set via environment/`.env`. It signs every JWT and (via HKDF) derives the evidence-key KEK
    — a real deployment MUST set a real, random `SECRET_KEY` via the hosting platform's environment
    variables, never commit one to source control.
  - `ADMIN_PASSWORD`/`INITIAL_OPERATOR_PASSWORD`/`INITIAL_AUDITOR_PASSWORD` default to
    `CHANGE_ME_*_password` placeholders, used only to bootstrap the three seed accounts on a first boot
    against an empty database — a fresh deployment MUST override these via environment variables before
    first boot, or anyone can look up the default in this repo and log in as admin.
  - `DATABASE_URL` defaults to SQLite locally (`sqlite:///./netraksh.db`, currently a 3.5MB real file
    with real seeded data in this repo). Most container-hosting platforms' filesystems are ephemeral —
    the database would be silently wiped on every redeploy/restart. `psycopg2-binary` is already in
    `requirements.txt` for exactly this reason; a real deployment needs an actual Postgres instance
    (managed or self-hosted) and `DATABASE_URL` pointed at it, not the SQLite default.
  - This repository is not a git repository at all (`git status` fails with "not a git repository") —
    there is no version history and nothing to push to a platform that deploys from a git remote.
  - No `Dockerfile` exists yet for a containerized deploy target.
- **Endpoint-level HTTP tests for the two evidence-image/evidence-key routes still do not exist.**
  **Update — `tests/integration/` and `tests/e2e/` are no longer empty for every endpoint**: a real
  integration/E2E layer was added (`tests/integration/test_backend_e2e.py`,
  `test_evidence_pipeline_e2e.py`, `test_edge_pipeline_real_video_e2e.py`) using FastAPI's real
  `TestClient` against `backend.main:app` (real routers, real RBAC, an isolated per-test SQLite DB)
  and the real `edge.main.EdgePipeline` against the real `demo/videos/vtest.avi` clip — covering
  real signed-event ingest + `POST /events/{id}/verify` (hash/signature/chain-continuity, including a
  forged signature and a broken chain link), RBAC enforcement (`ADMIN`/`OPERATOR`/`AUDITOR`) on
  `POST /cameras`, `POST /alerts/{id}/acknowledge`, and the auth-required routes, a real offline-
  outbox → real running backend sync round trip (`edge/sync/sync_client.py`'s `SyncClient` against a
  real `uvicorn` server on a loopback port, not a stub), the real hash-chain and AES-256-GCM
  snapshot-tamper detection paths (`EvidencePackager`/`EvidenceChainStore`/`EvidenceEncryptor`
  composed together, not just unit-tested in isolation), the real camera-health-FAILED → ABSTAIN →
  tiered-snapshot-capture path, and one full-clip run of the real `EdgePipeline` end to end. **Still
  not covered**: `GET /events/{event_id}/evidence-image` and `PUT /cameras/{id}/evidence-key`
  specifically (the decrypt-on-view HTTP path itself), and the WebSocket broadcast endpoints — the
  crypto/wrapping/migration logic each depends on remains fully unit-tested, but their HTTP wiring is
  not yet exercised by an automated test.

- **Cross-camera corroboration (`backend/services/cross_camera.py`, new) is temporal + real-distance
  plausibility only — it is NOT person re-identification.** No face/appearance embedding exists
  anywhere in this codebase that could confirm two sightings at different cameras are the same
  physical person. Two different people of the same `detection_class`, at geographically nearby
  cameras, within a physically-plausible travel-time window, WILL corroborate each other under
  this definition — this is why every place this score is surfaced (API field names, UI labels,
  this doc) says "corroboration", never "identity" or "same person". There is also no hand-entered
  camera topology graph with real measured ETAs (the poster's own "80m / ETA 8-30s" is
  illustrative demo data, not something honestly assertable about hardware never deployed);
  instead, distance comes from real haversine on each camera's real, admin-entered
  latitude/longitude, and the expected-travel-time range comes from that real distance and a
  disclosed, hand-picked walking-speed heuristic (0.8–2.2 m/s), not a measured one. The
  corroboration score is also deliberately never used to retroactively change an already-signed
  event's `decision_state`/confidence — see `docs/ARCHITECTURE.md`'s entry for why (tamper-evident
  chain-of-custody). **Update — now wired into escalation, on explicit user request:**
  `backend/services/escalation.py` treats a MEDIUM-severity event as escalation-eligible when it
  carries strong real corroboration (`corroboration_score >= 0.6` — much stricter than the 0.15
  threshold that merely gates whether anything is shown on the Evidence page, since this one gates
  a real alerting-behavior change). LOW is never boosted. The original `Event.severity` field
  itself is still never mutated; every alert created via this path is transparently marked
  `Alert.escalated_via_corroboration=True` (visible via `AlertResponse` and the Alerts page), never
  a silent change. See `docs/ARCHITECTURE.md`'s "Cross-Camera Corroboration Wired Into Escalation"
  entry for the full account.

## 3. Designed in architecture v4, not yet implemented in code

These are real, open gaps — tracked here so nothing is silently assumed to exist. Each links to the
architecture section that specifies it.

| Item | Architecture ref | Status |
|---|---|---|
| Adaptive compute gating's resolution tiers (higher-res crop on candidate-forming, full-res on verified) | v4 §6 | **Not implemented.** Only the idle/active inference-*rate* gating is built (`edge/detection/adaptive_gate.py`) — see §1 below. No tier changes resolution; there's nothing to "restore" resolution from. |
| Edge transmitting evidence bytes (not just a path) during sync, for a real distributed deployment | v4 §10 | **Not implemented.** `Event.evidence_clip_ref` is a local file path string; `edge/sync/sync_client.py` never uploads the actual snapshot. `GET /events/{event_id}/evidence-image` only works when the backend and edge share a filesystem, as they do in this project's current deployment — see §1 above. |
| Re-running the false-positive measurement against real staged demo footage | v4 §11, `docs/PERFORMANCE_REPORT.md` | **Partially closed.** Re-run against MOT16-04 (real, denser, occluded street footage — see `docs/PERFORMANCE_REPORT.md`'s "Re-run against real, denser footage" entry) found a real 14.3% alert reduction from the Event Verifier, closing the specific "needs footage with real tracking jitter" gap the original `vtest.avi` run identified. Still **not** the team's own staged demo footage or intrusion scenario — that genuinely doesn't exist and can't be fabricated (no camera, location, or actors to film) — and still doesn't cover night/fog/glare conditions — see §1 below. |
| `EventState.CLOSED` — the terminal state of the Event Verifier lifecycle (OBSERVED → CANDIDATE → VERIFIED → ALERTED → ACKNOWLEDGED → CLOSED) | v4 §9, §11 | **Closed.** `POST /alerts/{id}/close` (`backend/api/alerts.py`) sets a real, queryable `Alert.lifecycle_state = "CLOSED"`, enforcing the real order (an alert must already be acknowledged first). See `docs/ARCHITECTURE.md`'s "Real Alert 'Close' Action" entry for the full account. |
| Dashboard visualization of the Event Verifier's OBSERVED/CANDIDATE/VERIFIED progression, Track Continuity Guard re-associations, and Night-Motion Fallback firings | v4 §4, §9 | **Not implemented.** All three run for real on the edge (`edge/main.py` wires `EventVerifier`, `TrackContinuityGuard`, `NightMotionFallback` into the real per-frame loop) but have no dashboard page showing their state — unlike the Adaptive Compute Gate, whose real ACTIVE/IDLE state and skip ratio genuinely reach the Performance page. A real, correctly-functioning backend mechanism with zero UI visibility looks unfinished from the dashboard alone, which is a fair thing to flag even though the underlying engine isn't the gap. |

## 4. What IS real and measured (as of this writing)

- Camera health (frozen-frame, blur, exposure, FPS ratio, clock drift) and scene condition
  (brightness/contrast/glare) are computed from real OpenCV/numpy signal processing on every frame —
  not simulated.
- YOLOv8n + ByteTrack detection/tracking is real, running via `ultralytics`.
- The Event Verifier state machine (CANDIDATE → VERIFIED/ALERTED, confirmation-gated) is implemented
  and unit-tested (`tests/unit/test_event_verifier.py`).
- The Hybrid Reliability Engine (Gate-1 hard override + weighted-sum `R = wD·D+wT·T+wS·S+wH·H`) is
  implemented and unit-tested (`tests/unit/test_reliability.py`), including a deliberate, documented
  behavior change from the original cascade (see `docs/ARCHITECTURE.md`). Its weights are real code,
  not a slide — but see §1 above for their calibration status.
- Temporal Evidence Intelligence Mode A (track age, path smoothness, speed consistency →
  `T`) is implemented and unit-tested (`tests/unit/test_track_features.py`), per the no-SSM decision
  recorded in `docs/ADR-TEMPORAL.md`.
- The Track Continuity Guard (border-tuned ByteTrack `track_buffer` + classical-CV color-histogram
  re-association) is implemented and unit-tested (`tests/unit/test_continuity_guard.py`,
  `tests/unit/test_detector_tracker_config.py`) — but see §1 above for its threshold-calibration
  status.
- Line crossing (`edge/rules/modules.py::LineCrossingModule`) is implemented and unit-tested
  (`tests/unit/test_line_crossing.py`), routed through the same Event Verifier confirmation logic as
  fence crossing — but see §1 above: it has no configured zones to actually fire against yet.
- The Adaptive Compute Gate (idle/active inference-rate scheduling) is implemented and unit-tested
  (`tests/unit/test_adaptive_gate.py`), with its skip ratio logged and persisted alongside the rest of
  the real performance instrumentation — but see §1 above for its threshold-calibration status, and
  see §3 above for the resolution-tiering half of v4 §6 that isn't built.
- CLAHE preprocessing and the night-motion fallback are both implemented and unit-tested
  (`tests/unit/test_preprocessing.py`, `tests/unit/test_night_motion_fallback.py`) — the latter
  closing out real, previously-dead code, not new logic from scratch. Both are mitigations with
  hand-picked parameters; see §1 above for exactly what that does and doesn't claim.
- The offline sync queue is priority-ordered (`severity DESC, sequence_number ASC`) and unit-tested
  (`tests/unit/test_sync_client_priority.py`), including a migration path verified against the actual
  pre-existing `edge/data/sync.db` in this repo, not just a synthetic test database.
- Backend decrypt-on-view for encrypted evidence is implemented (`shared/crypto.py`,
  `backend/security/evidence_key_wrap.py`, `PUT /cameras/{id}/evidence-key`,
  `GET /events/{id}/evidence-image`) and its crypto/wrapping/migration logic is unit-tested — but see
  §1 above for the single-machine deployment constraint, the KEK's security tradeoff, and the
  untested HTTP layer.
- The frontend now actually calls that endpoint (`frontend/src/pages/Evidence.jsx`, via the new
  `frontend/src/services/auth.js`) instead of it only proving itself over curl — including the
  minimal login flow this required, since the frontend previously had no auth infrastructure at all.
  Verified via a real `vite build` and lint pass, not an automated test — this project has no frontend
  test suite yet, a pre-existing gap.
- The Dashboard's Reliability Decision panel (`frontend/src/pages/Dashboard.jsx`) now shows the real
  D/T/S/H factors, R score, and threshold parsed from the real `decision_reason` string, instead of
  hardcoded placeholder values — verified end-to-end by POSTing a real event through the real
  ingestion endpoint and confirming the rendered numbers in a live screenshot, not just reading the
  code. The dashboard's "Demo Scenario Control" panel (Normal Ops / Dense Fog / Sensor Failure /
  Offline buttons) was later confirmed (not just left unverified) to call backend routes that don't
  exist at all — see the frontend audit entry below.
- **Camera Health Matrix, Cross-Command Alerts, and the Dashboard's video overlay label are now wired
  to real backend data** (a full audit + fix pass — see `docs/ARCHITECTURE.md`'s "Frontend Audit + Full
  Real-Data Wiring Pass" for complete detail on each). Summary: `GET /cameras` is now actually called
  (it never was); a real `POST /cameras/{id}/health` ingestion endpoint was added because the backend
  had never once written a `CameraHealth` row despite the edge computing real values every frame;
  `GET /alerts` is now actually called and the 2 hardcoded fake alerts that used to be permanently
  mixed into the real WS feed are now a true empty-state fallback only; the video overlay's detection
  label now uses the real event's `detection_class`/`track_id`/`confidence` instead of a hardcoded
  placeholder that could never be replaced (the dead `eventData.bbox` check it depended on can never
  be true — `EventResponse` has no `bbox` field). The header's "⚠ 04" alert badge is now a real count
  from `/system/status`'s `pending_acknowledgements`.
- **A second `/health`-class route collision was found and fixed:** the frontend's `/alerts` SPA route
  collided with the real backend route `GET /alerts`, identically to the earlier `/health` collision.
  Renamed to `/cross-command-alerts`. Every remaining frontend route was then checked against every
  backend router prefix to confirm no further collisions exist.
- **A real, previously-latent 500 error in `GET /cameras` was found and fixed:** `_camera_to_response()`
  passed the literal string `"UNKNOWN"` as a `CameraHealthState` for any camera with no health row yet
  — but that enum only has `OK`/`DEGRADED`/`FAILED`. This endpoint would 500 for every real camera in
  the database until its very first health report, which (see above) had never happened for any camera
  before this pass, meaning this endpoint had never once returned successfully for real camera data.
  Fixed by making `CameraStatusResponse.health_state` `Optional`.
- Zone matching (`edge/rules/modules.py::normalize_point`) is now resolution-independent and
  unit-tested end-to-end at two different frame sizes from the same config
  (`tests/unit/test_zone_normalization.py`) — closing a real bug where raw-pixel comparisons against
  an undefined coordinate unit would silently misbehave on any camera resolution other than whatever
  one the config happened to be authored against.
- The Hybrid Reliability Engine's filtering effect is measured, not just designed: on a real 795-frame
  test clip, it independently reduced 52 raw fence-crossing candidates to 23 (`docs/
  PERFORMANCE_REPORT.md`) — but see §1 above for what that same run does and does not show about the
  Event Verifier specifically.
- Evidence hashing (SHA-256), signing (Ed25519), and hash-chaining (append-only SQLite) are real
  cryptography, not placeholders — including tamper detection on chain verification.
- Evidence-at-rest encryption (AES-256-GCM) is real and active for every snapshot written to disk.
- Offline store-and-forward uses a real, durable SQLite queue with ordered, retry-on-failure upload —
  not an in-memory structure that would be lost on restart.
- Pipeline performance instrumentation (`edge/instrumentation/metrics.py`) measures real
  `time.perf_counter()` latency at every stage and real FPS from actual frame timestamps — CPU/RAM
  are real `psutil` readings when installed, `null` otherwise, never fabricated. No number in
  `docs/PERFORMANCE_REPORT.md` should ever be filled in by hand; only paste what this instrumentation
  actually printed.
