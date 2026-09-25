# Phase 4 WP-4.4: Degradation Policy

## No Silent Quality Degradation
NETRAKSH strictly prevents false negative conclusions (e.g., claiming "no face detected" when face processing was skipped to save CPU).
When a module is shed due to resource pressure, it must emit a state akin to `NOT_EVALUATED_RESOURCE_PRESSURE`.

## Module Degradation Matrix

| State | Detection | Tracking | ANPR | Face | Behavior | Evidence | Telemetry |
|---|---|---|---|---|---|---|---|
| **NORMAL** | Every Frame | Every Frame | Every Configured Frame | Every Configured Frame | Every Frame | Preserved | Standard Cadence |
| **WARNING** | Every Frame | Every Frame | Reduced Cadence (e.g., 1/2) | Reduced Cadence | Reduced Cadence | Preserved | Standard Cadence |
| **DEGRADED** | Every Frame | Every Frame | Cadence 1/5 (if critical) else Skipped | Cadence 1/5 (if critical) else Skipped | Cadence 1/5 | Preserved | Reduced Cadence |
| **CRITICAL** | Every Frame | Every Frame | Cadence 1/10 (if critical) else Skipped | Cadence 1/10 (if critical) else Skipped | Core Safety Only | Preserved | Minimal |

### Module Criticality Configuration
Modules like ANPR and Face can be designated as critical via `ANPR_CRITICAL=true` and `FACE_CRITICAL=true`. If critical, they will maintain a reduced evaluation cadence under severe pressure instead of being fully skipped.

Core Detection and Tracking are *always* critical and are never shed.
