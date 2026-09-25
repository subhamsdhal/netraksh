# Phase 4 WP-4.4: Resource Architecture

## Overview
NETRAKSH Edge employs a bounded resource governance model designed to protect nodes from overload (OOM, thermal throttling, stream starvation) without sacrificing core safety capabilities.

## EdgeResourceGovernor
The `EdgeResourceGovernor` runs inside the edge node and tracks system health metrics independently of Central via `psutil`.

**Metrics Tracked:**
- Overall CPU utilization
- Total System RAM usage
- Average Queue Depth (from local Stream Ingestion components)
- Average Inference Latency

### State Machine & Hysteresis
The governor maps instant metrics to four states:
1. **NORMAL:** Utilization is well within limits.
2. **WARNING:** Nearing thresholds; early proactive measures required.
3. **DEGRADED:** System is struggling; optional workloads must be shed.
4. **CRITICAL:** Threshold exceeded; imminent risk to core function.

To prevent rapid toggling between states (oscillation), state transitions employ **hysteresis**. The governor will immediately escalate to a worse state to preserve safety, but it will only downgrade to a better state if the improved metrics persist for a configured period (e.g. `RESOURCE_HYSTERESIS_SECONDS`).
