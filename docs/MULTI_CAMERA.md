# Multi-Camera Intelligence

## Overview

NETRAKSH implements multi-camera intelligence primarily via spatial-temporal corroboration, with an optional classical appearance correlation engine introduced in Phase 3 Step 8.

The cross-camera architecture is fundamentally designed around the philosophy of **Plausibility, Not Identity**. The system explicitly avoids black-box neural "Re-ID" claims, choosing instead to correlate sightings across different camera views using transparent, explainable logic.

## Baseline (Spatial-Temporal)

By default (`CROSS_CAMERA_REID=disabled`), the system uses only real physical signals to establish corroboration:
- **Haversine Distance**: Derived from real camera GPS coordinates.
- **Expected Travel Time (ETA)**: Derived from conservative human walking-speed heuristics applied to distance.
- **Temporal Consistency (Tc)**: An exponential decay function $Tc = e^{-|\Delta t - t_{expected}| / \sigma}$ evaluating how closely the actual time gap matches the expected transit time.

## Enhanced (Appearance-Correlated)

When `CROSS_CAMERA_REID=appearance` is set in the backend configuration, the system incorporates an additional `CLASSICAL_APPEARANCE_DESCRIPTOR` (a deterministic color histogram converted to HSV space, L2 normalized, and compared via cosine similarity).

### Absolute Rules & Limitations

1. **Not Neural Re-ID**: The system explicitly does not use learned Re-ID neural networks. A color histogram cannot distinguish between two people wearing similarly colored clothing.
2. **Privacy**: Embeddings are never stored permanently in the database. They are cached in-memory with a bounded TTL (default 30 minutes) and discarded. No embeddings are hashed to the blockchain.
3. **Explicit Correlation States**: The engine maps matching into explicit states rather than a single collapsed probability:
    - `CORROBORATED`: Temporally plausible and visually similar.
    - `CONFLICTED`: Temporally plausible but visually conflicting.
    - `CANDIDATE`: Temporally plausible but appearance check unavailable/uncertain.
    - `NO_MATCH`: Not temporally plausible or too distant.
    - `INSUFFICIENT_EVIDENCE`: Missing real coordinate data or image crops.

These rules ensure NETRAKSH continues to operate with verifiable, privacy-first evidence, rejecting fabricated AI confidence claims in favor of deterministic mathematics.
