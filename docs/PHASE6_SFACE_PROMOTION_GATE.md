# PHASE 6: SFACE PROMOTION GATE

## Status
BLOCKED (Pending Evaluation Dataset)

## Objective
Establish rigorous promotion criteria that must be satisfied before SFace replaces LBPH as the default recognition engine in NETRAKSH.

## Gate Requirements
The `PromotionGate` logic enforces that ALL of the following conditions must be met:
1. **Approved Dataset**: The evaluation dataset must clear the `DatasetValidator` with a `DATASET_APPROVED` status. This requires explicit identities, verified license, valid hashes, sufficient sample counts, and no split leakage.
2. **Reproducible Pair Generation**: All evaluation must use the deterministic `PairGenerator` logic, securing pairs via `dataset_hash` without logging the raw biometrics.
3. **ROC/EER Analysis**: Metrics must be mathematically computable across threshold sweeps without fabricating samples.
4. **Condition Slice Analysis**: Metadata slices (e.g. DAY, NIGHT, OCCLUSION) must exist and return statistically valid TAR@FAR rates.
5. **Temporal Integration**: SFace must maintain seamless integration with `TemporalFaceFusion` and yield measurable candidate validation rates in video evaluation data.
6. **Regression**: Tests verifying LBPH default status, fallback status, and resource pressure behavior must continue to pass (`tests/test_phase6_sface_integration.py`).
7. **Privacy Constraints**: Absolutely no raw embeddings or face images may be emitted into logs, metrics payloads, or saved arrays.

## Current Promotion Decision
**PROMOTION = BLOCKED**
**DEFAULT ENGINE = LBPH**
**SFACE = OPT-IN**

The codebase lacks domain-specific validation data with border-CCTV ground truth. 
Therefore, promotion is legally and mathematically blocked.

## EVALUATION DATASET PROCUREMENT

### 1. DATASETS INVESTIGATED

**CANDIDATE 1: Labeled Faces in the Wild (LFW)**
- **Dataset Version**: Original
- **Official Source**: UMass Amherst
- **Official Download**: http://vis-www.cs.umass.edu/lfw/
- **Dataset Owner**: Gary B. Huang, et al.
- **License**: Academic / Non-commercial Research
- **Commercial Use**: RESTRICTED
- **Redistribution**: RESTRICTED
- **Identity Labels**: YES (Verification pairs)
- **Verification Pairs**: YES
- **Condition Metadata**: NO
- **Temporal Data**: NO
- **Identity Count**: ~5,749
- **Sample Count**: 13,233
- **Surveillance Relevance**: GENERIC FACE RECOGNITION
- **Known Limitations**: Web photos, mostly frontal, no CCTV conditions.
- **NETRAKSH Status**: REJECTED (License prohibits commercial use; irrelevant domain)

**CANDIDATE 2: QMUL-SurvFace**
- **Dataset Version**: 2018
- **Official Source**: Queen Mary University of London
- **Official Download**: https://qmul-survface.github.io/
- **Dataset Owner**: QMUL Computer Vision Group
- **License**: End User License Agreement (EULA) required
- **Commercial Use**: DENIED (Academic research only)
- **Redistribution**: DENIED
- **Identity Labels**: YES
- **Verification Pairs**: YES
- **Condition Metadata**: YES (Low res, blur)
- **Temporal Data**: NO (Cropped bounding boxes)
- **Identity Count**: 15,573
- **Sample Count**: 463,507
- **Surveillance Relevance**: SURVEILLANCE-LIKE FACE RECOGNITION
- **Known Limitations**: Extremely low resolution (often 24x24), severe license restrictions.
- **NETRAKSH Status**: REJECTED (Strict academic non-commercial license)

**CANDIDATE 3: IARPA Janus Benchmark-C (IJB-C)**
- **Dataset Version**: IJB-C
- **Official Source**: NIST / IARPA
- **Official Download**: https://www.nist.gov/
- **Dataset Owner**: NIST
- **License**: NIST Research Agreement
- **Commercial Use**: DENIED (Research/evaluation only for signatories)
- **Redistribution**: DENIED
- **Identity Labels**: YES
- **Verification Pairs**: YES
- **Condition Metadata**: YES
- **Temporal Data**: YES (Video frames)
- **Identity Count**: 3,531
- **Sample Count**: 31,334 (Images) + 11,754 (Videos)
- **Surveillance Relevance**: SURVEILLANCE-LIKE FACE RECOGNITION
- **Known Limitations**: Requires signed agreement, highly restricted distribution.
- **NETRAKSH Status**: REJECTED (License and provenance restrictions)

### 2. DATASET COMPARISON TABLE

| Dataset | License | Ground Truth | Pairs | Condition Metadata | Temporal Data | Surveillance Relevance | Reproducibility | NETRAKSH Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **LFW** | Non-Commercial | Yes | Yes | No | No | Generic FR | High | **REJECTED** |
| **QMUL-SurvFace**| Academic Only | Yes | Yes | Yes | No | Surveillance-like | High | **REJECTED** |
| **IJB-C** | NIST Release | Yes | Yes | Yes | Yes | Surveillance-like | High | **REJECTED** |

### 3. RECOMMENDATION
- **PRIMARY CANDIDATE**: NONE
- **SECONDARY CANDIDATE**: NONE
- **REJECTED CANDIDATES**: LFW, QMUL-SurvFace, IJB-C, MS-Celeb-1M, MegaFace

**NO DATASET APPROVED.**

The strict requirement for open commercial usage combined with border-CCTV domain relevance eliminates all major public datasets. Any deployment of SFace to production will require a Custom Collection of border data with explicit, GDPR-compliant consent/release forms.
