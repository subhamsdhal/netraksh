# LPD_YuNet Test Matrix

Executed via `tests/test_phase6_anpr_lpd_yunet.py`

| Test Category | Scenario | Outcome |
|---|---|---|
| Initialization | valid artifact available | PASSED |
| Initialization | artifact missing | PASSED (isolated failure) |
| Localization | coordinate transform bounding box | PASSED |
| Localization | degenerate quadrilateral rejection | PASSED |
| Filtering | low contrast | PASSED |
| Integration | Legacy heuristic selected | PASSED |
| Integration | Temporal fusion validation | PASSED |

No regressions observed in base logic. Legacy pipeline executes unaffected when `ANPR_ENGINE='heuristic'`.
