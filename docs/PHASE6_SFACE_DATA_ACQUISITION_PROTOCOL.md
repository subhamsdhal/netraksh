# PHASE 6: SFACE DATA ACQUISITION PROTOCOL

## 1. PURPOSE & SCOPE
This document formally defines the **NETRAKSH INTERNAL SFACE EVALUATION DATASET** protocol.
- **Purpose**: Lawful evaluation of face verification thresholds, false-match / false-non-match rates, and temporal fusion behavior for SFace.
- **Explicit Scope Limitation**: This dataset is **NOT** a production watchlist. It is **NOT** to be used to make operational identity decisions. It exists exclusively for controlled model evaluation.

## 2. DATA MODEL & IDENTITY REGISTRY
To enforce strict privacy boundaries:
- The **Identity Registry** (names, consent records, demographic data) is physically and logically separated from the **Biometric Evaluation Data**.
- The evaluation system and pairs generator operate **only** using pseudonymous participant IDs (e.g. `P_001`, `P_002`).

## 3. CONSENT & GOVERNANCE DOCUMENTATION
For every participant, the data controller must legally record:
- `consent_id`
- `participant_pseudonym`
- `collection_date`
- `collection_purpose`
- `authorized_use`
- `evaluation_scope`
- `retention_period`
- `withdrawal_policy`
- `storage_location`
- `access_policy`
- `version`
- `signature_or_verified_acceptance_reference`

**Mandatory Governance Controls:**
*LEGAL REVIEW REQUIRED | JURISDICTION REQUIRED | DATA CONTROLLER / RESPONSIBLE PARTY REQUIRED | LAWFUL BASIS REQUIRED | RETENTION POLICY REQUIRED | SECURITY CONTROLS REQUIRED*

## 4. COLLECTION PROTOCOL
Data is captured through *Natural Capture* scenarios mimicking border surveillance, strictly distinguishing real-world capture from *Synthetic Augmentation*. Target slices:
- DAY
- LOW_LIGHT
- BLUR
- MOTION
- PARTIAL OCCLUSION (Masks, Sunglasses, Headgear)
- POSE (Pitch/Yaw variations)
- DISTANCE (Scale)
- GLARE

## 5. TEMPORAL DATA PROTOCOL
For evaluating sequential `TemporalFaceFusion` performance, the collection must retain video sequences. Sequence annotation fields:
- `participant_id`
- `sequence_id`
- `frame_index`
- `timestamp`
- `track_ground_truth`
- `capture_condition`

## 6. PAIR GENERATION (GENUINE/IMPOSTOR)
Evaluation pairs are constructed deterministically utilizing a controlled seed.
- **Genuine**: Same authorized pseudonymous identity across disjoint samples.
- **Impostor**: Different authorized pseudonymous identities.
- **Constraints**: Seed tracking, no cross-split leakage, explicit hash bindings for pairs list (`pair artifact hash`).

## 7. DATA SPLITS
- **DEVELOPMENT**: Initial system shakedown.
- **VALIDATION**: Used exclusively for threshold calibration and tuning.
- **TEST**: Held-out split. **Prohibitions**: No tuning on the test set, no repeated threshold sweeping after witnessing test results, no conflating validation and test performance.

## 8. PROVENANCE BINDING
Every evaluation artifact MUST bind to the dataset version and hash. The `DatasetProvenance` schema enforces validation over fields such as `collection_protocol_version`, `legal_review_reference`, `data_controller`, and `deletion_policy`.

## 9. PRIVACY CONTROLS
**Strictly Prohibited Logging:**
- Raw face images
- Raw/serialized embeddings
- Biometric tensors
- Identity names or contact details

**Security Enforcement:**
Encryption at rest, strict access controls, audit logging, adherence to retention limits, secure deletion protocols, and regulated backup policies.

## 10. APPROVAL GATE
A dataset is assigned `APPROVED_FOR_SFACE_EVALUATION` ONLY when all evidence exists (provenance, ground truth, condition metadata, consent, legal review, and storage controls). Otherwise, the dataset remains `BLOCKED`.

## 11. SFACE PROMOTION WORKFLOW
```text
DATASET APPROVAL
↓
PAIR GENERATION
↓
VALIDATION THRESHOLD SWEEP
↓
THRESHOLD FREEZE
↓
FINAL TEST
↓
ROC / FAR / FRR / TAR@FAR / EER
↓
CONDITION SLICES
↓
TEMPORAL EVALUATION
↓
PROMOTION REVIEW
```

## 12. CURRENT PROJECT STATUS
- **SFace Engine**: OPT-IN
- **LBPH Engine**: DEFAULT
- **Threshold**: NOT CALIBRATED
- **Ground Truth**: UNAVAILABLE
- **Promotion Status**: BLOCKED

## 13. CURRENT BLOCKER
The initiation of the SFace threshold calibration and evaluation sweep is explicitly blocked pending the physical, lawful acquisition and approval of the internal evaluation dataset per this protocol.
