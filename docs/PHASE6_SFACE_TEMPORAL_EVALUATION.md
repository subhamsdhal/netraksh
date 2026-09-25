# PHASE 6: SFACE TEMPORAL EVALUATION

## Status
NOT MEASURABLE — NO VALID GROUND TRUTH

## Objective
Evaluate how raw frame-level SFace matches are filtered, smoothed, and confirmed by the `TemporalFaceFusion` subsystem over time on a video stream.

## Metrics Pending
Because we lack a video-level evaluation dataset (i.e. contiguous tracked sequences of border faces), we cannot measure:
- **Candidate Rate**: Frequency of initial frame-level matches.
- **Confirmation Rate**: Percentage of candidates graduating to `CONFIRMED`.
- **False Confirmation Rate**: Confirmed identities that were incorrect.
- **Confirmation Latency**: Time/frames required to reach a stable confirmation.
- **Unstable Rate**: Matches discarded due to flickering identity transitions.

## Subsystem Integration Status
- The structural integration of SFace into the legacy pipeline **preserves** all temporal fusion semantics exactly as designed in earlier phases.
- The distinction between `UNKNOWN` and `CONFIRMED` remains purely controlled by fusion state rules.
- If SFace yields a non-zero similarity below the matching threshold, it emits `UNKNOWN` which decays evidence, preventing false confirmations due to low-confidence vectors.
- If resource pressure causes SFace inference to be skipped (via WP-4.4), it emits `NOT_EVALUATED_RESOURCE_PRESSURE`, cleanly avoiding `UNKNOWN` penalties.
