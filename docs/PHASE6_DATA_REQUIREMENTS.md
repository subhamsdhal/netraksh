# Phase 6: Dataset Requirements

## 1. General Principles
- No public dataset (e.g. COCO, LFW) is pre-authorized. Any dataset must pass the Provenance Gate.
- The evaluation must eventually run against CUSTOM / BORDER-SPECIFIC datasets to be valid for production.
- **NO DOWNLOADING** of internet datasets is permitted without strict Provenance and License clearance.

## 2. ANPR Dataset Schema
Ground truth must be formatted (e.g., JSON/COCO-style) containing:
- `image_id` / `frame_id`
- `camera_id`, `timestamp`
- `vehicle_id` (for temporal tracking)
- Bounding Box: `[x, y, w, h]`
- `transcript`: Exact text
- **Condition Slices**: `visibility`, `quality`, `occlusion`, `lighting` (day/night/glare), `blur`, `view_angle`, `distance_category`, `weather_condition`.

## 3. Face Recognition Dataset Schema
Ground truth must contain:
- `image_id` / `frame_id`
- `camera_id`, `timestamp`
- `subject_identity` (Pseudonymous ID)
- Bounding Box: `[x, y, w, h]`
- `landmarks`: (e.g., 5-point facial landmarks if available)
- **Condition Slices**: `pose` (frontal/profile), `occlusion`, `illumination` (backlit/low-light), `distance` (long-range), `image_quality`, `blur`.

## 4. Unknown Protocol
The Face dataset must include instances of:
- Known identities
- Unknown identities (impostors)
- Low-quality faces
The system must correctly classify impostors/low-quality inputs as `UNKNOWN` or `CANDIDATE` rather than forcing a false positive match.

## 5. Splitting Strategy (Train/Val/Test)
- Identities must not leak across splits.
- For video sequences, splits occur at the camera/sequence level, not by randomly shuffling adjacent frames.

## 6. Data Provenance Record Structure
- `dataset_name`, `version`, `source_url`
- `license` (Image/Annotation)
- `redistribution_permission`, `commercial_use_permission`, `privacy_restrictions`
- `status`: `VERIFIED`, `UNVERIFIED — DO NOT USE`, `REJECTED`
