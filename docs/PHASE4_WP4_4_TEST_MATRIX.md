# Phase 4 WP-4.4: Test Matrix

## Test Suite: `tests/test_wp4_4_resource_management.py`

| Test Case | Description | Status |
|---|---|---|
| `test_governor_initial_state` | Validates default `NORMAL` startup. | EXECUTABLE |
| `test_governor_warning_transition` | Validates mock CPU metrics correctly trigger `WARNING`. | EXECUTABLE |
| `test_governor_critical_transition` | Validates queue pressure exceeding bounds triggers `CRITICAL`. | EXECUTABLE |
| `test_hysteresis_prevents_rapid_recovery` | Validates state doesn't downgrade to normal without wait delay. | EXECUTABLE |
| `test_admission_hard_limit` | Validates streams > `MAX_ACTIVE_STREAMS` are rejected instantly. | EXECUTABLE |
| `test_admission_reject_low_in_warning`| Validates `LOW` priority streams are rejected during `WARNING` state. | EXECUTABLE |
| `test_admission_accept_degraded_in_degraded` | Validates `HIGH` priority streams are partially accepted in `DEGRADED`. | EXECUTABLE |
| `test_degradation_policy_normal` | Validates full evaluation occurs normally. | EXECUTABLE |
| `test_degradation_policy_warning_cadence` | Validates evaluated modules use partial skip cadence in `WARNING`. | EXECUTABLE |
| `test_degradation_policy_critical_skips_optional` | Validates non-critical ANPR is fully skipped in `CRITICAL`. | EXECUTABLE |
| `test_degradation_policy_critical_preserves_critical_modules` | Validates ANPR retains partial cadence in `CRITICAL` if flagged as critical. | EXECUTABLE |

## Regression Execution
**STATUS:** NOT EXECUTED — ENVIRONMENT BLOCKED (Execution requires functioning pytest/psutil setup on node).
