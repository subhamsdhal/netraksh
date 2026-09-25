# ADR-001: Temporal Evidence Intelligence uses hand-crafted features, not a sequence model

**Status:** Accepted
**Date recorded:** architecture v4 revision (§7)
**Applies to:** the "Temporal Evidence Intelligence" block in the pipeline diagram, and the `T`
factor in the Reliability Engine (`R = w1·D + w2·T + w3·S + w4·H`, see `docs/ARCHITECTURE.md` and
`NETRAKSH_Architecture_v4_Final`).

## Context

An earlier version of the architecture ("poster deck" / v3 review) proposed implementing "Temporal
Evidence Intelligence" as a Mamba/state-space model (SSM) consuming track history, trajectory
evolution, motion pattern, and repeated behavior. A GRU or 1D-CNN sequence model was also floated as
an alternative. Both are real, legitimate modeling approaches in general — but not for this project,
at this stage, on this timeline.

## Decision

**Temporal Evidence Intelligence for MVP is implemented as hand-crafted trajectory features, computed
per track over a rolling ~30–90 frame window:**

- `dwell_seconds` — time continuously inside the current zone
- `path_smoothness` — 1 / (1 + variance of frame-to-frame heading-angle change)
- `speed_mean`, `speed_norm` — centroid displacement per second, normalized by frame diagonal
- `revisit_count` — distinct times this track has entered the same zone in the session
- `track_age_seconds` — time since the track was first observed

These combine into `T ∈ [0,1]` via one of two modes:

- **Mode A (default, ships with zero labeled data required):** a hand-weighted, explicitly-labeled
  linear combination of the normalized features above.
- **Mode B (upgrade path, only if 200–500 labeled clips become available):** a plain
  `sklearn.linear_model.LogisticRegression` over the same 5 features against labeled true/false
  event outcomes. This is a small **tabular** classifier, not a sequence model — it does not revisit
  any part of this decision.

**No Mamba/SSM, no GRU, no LSTM, no 1D-CNN over raw track sequences is in scope for MVP or Phase 2.**
If Mode B is ever outgrown, the next step (if any) is Phase 3+ scope, and requires a new ADR.

## Why (the three reasons this was rejected, recorded so they don't need re-litigating)

1. **No training data.** SSMs, like any learned sequence model, need labeled examples of "normal"
   vs. "loitering" vs. "suspicious" trajectory sequences to be useful. The team does not have this
   dataset, and building one from scratch is its own multi-week project — not something a hackathon
   timeline supports.
2. **Wrong tool for the sequence length.** Mamba/SSM architectures earn their keep on very long
   sequences (thousands of steps) where attention-based models get expensive. A border-camera track
   history is comparatively short (tens to low hundreds of frames). Hand-crafted features — or, at
   most, a small tabular classifier over summary statistics of that short sequence — are a
   better-fitted, lower-risk tool for this problem size.
3. **It contradicts the team's own roadmap.** Every other planning artifact (the Phase 1/2/3 roadmap
   panel, the v3 and v4 architecture reviews) places advanced sequence modeling in Phase 2/3 at the
   earliest. A sequence model appearing in the MVP architecture diagram was an inconsistency between
   documents, not a considered scope decision — this ADR resolves that inconsistency in the direction
   the roadmap already agreed on.

## Consequences

- This decision **must not be silently revisited under deadline pressure.** If anyone on the team
  proposes reaching for an SSM, GRU, or LSTM for this component — especially in the final days before
  submission — point them to this ADR first, and require a written argument for why all three reasons
  above no longer apply before reopening the decision. "It sounds more advanced" is not such an
  argument; "we now have N labeled examples and M spare days to validate it" might be.
- Mode A must ship regardless of how Mode B's labeling effort goes — it is the non-negotiable
  fallback that requires zero data and is honest, explainable, and fast to build.
- If Mode B is built, its weights and evaluation must be reported the same way the Gate 3 calibration
  module (`edge/detection/calibration.py`) already reports isotonic/Platt calibration: labeled, with
  the sample size and validation method stated, never presented as more validated than it is.

## Implementation status as of this writing

- **Event Verifier** (the CANDIDATE → VERIFIED/ALERTED state machine, `edge/temporal/event_verifier.py`)
  **is implemented** — it gates on a confirmation count plus the Hybrid Reliability Engine's
  DETECTED/UNCERTAIN state.
- **Mode A is implemented** — `edge/temporal/track_features.py::TrackFeatureTracker` computes `T`
  from track age, path smoothness, and speed consistency, feeding the Hybrid Reliability Engine
  (`edge/reliability/decision.py`, see `docs/ARCHITECTURE.md`'s changelog entry). It needs zero
  labeled training data, exactly as specified above.
- **Scope reduction, recorded honestly (see `docs/LIMITATIONS.md`):** Mode A as built covers 3 of the
  5 features originally named in architecture v4 §7 — dwell-time-in-zone and revisit-count are not
  yet wired from `BehaviorModule`'s existing zone-scoped bookkeeping into `T`. This does not weaken
  this ADR's decision (no SSM/GRU either way) — it's an open, tracked gap in Mode A's feature set, not
  a reason to reach for a different modeling approach.
- **Mode B (LogisticRegression over labeled clips) is NOT implemented.** No labeled dataset exists
  yet to fit it against.
