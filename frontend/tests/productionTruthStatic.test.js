import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

describe('production UI contains no retired operational claims', () => {
  it('uses backend command identity and server-derived acknowledgement identity', () => {
    expect(read('../src/components/Header.jsx')).not.toContain('Sector Alpha');
    const alerts = read('../src/pages/Alerts.jsx');
    expect(alerts).not.toContain('Network Secure');
    expect(alerts).not.toContain("receiving_command_id: 'COMMAND_A'");
  });

  it('does not auto-start a camera or label a production slot as a demo slot', () => {
    const dashboard = read('../src/pages/Dashboard.jsx');
    expect(dashboard).not.toContain('SIH DEMO SLOT');
    expect(dashboard).not.toContain('autoStartedDemoCamerasRef');
    expect(dashboard).not.toContain('DEMO_CAMERA_LABELS');
  });

  it('uses lifecycle status instead of primary evaluator START or STOP controls', () => {
    const dashboard = read('../src/pages/Dashboard.jsx');
    expect(dashboard).toMatch(/analysisLifecyclePresentation\(\s*sourceState,\s*mediaState,/);
    expect(dashboard).toContain('RETRY ANALYSIS');
    expect(dashboard).not.toContain('START / ANALYZE');
    expect(dashboard).not.toContain('STOP ANALYSIS');
    expect(dashboard).not.toContain('data-action="stop-analysis"');
    // The normal backend stop contract remains available for operational use.
    expect(read('../src/utils/dashboardVideoControl.js')).toContain("payload.control_action = 'stop'");
  });

  it('uses shared freshness and age truth in the command center', () => {
    const dashboard = read('../src/pages/Dashboard.jsx');
    expect(dashboard).toContain('cameraHealthPresentation(health[activeCameraId], now)');
    expect(dashboard).toContain('formatTelemetryAge(telemetryAgeMs)');
    expect(dashboard).not.toContain('telemetryAgeMs / 1000).toFixed(1)');
  });

  it('keeps camera-card event selectors independent of table presentation state', () => {
    const dashboard = read('../src/pages/Dashboard.jsx');
    expect(dashboard).toContain('eventsForCameraRun(scopedRunEvents, cameraId, sessionId, streamId)');
    expect(dashboard).toContain('latestPlateEventForSession(cameraRunEvents, cameraId, sessionId, streamId)');
    expect(dashboard).toContain('latestFaceEventForSession(cameraRunEvents, cameraId, sessionId, streamId)');
    expect(dashboard).not.toContain('const cameraEvents = displayEvents.filter');
    expect(dashboard).not.toContain("if (eventCameraFilter !== 'ALL' && e.camera_id !== eventCameraFilter) return;");
  });

  it('does not present invented reliability, count, or correlation values', () => {
    const dashboard = read('../src/pages/Dashboard.jsx');
    expect(dashboard).not.toContain('let threshold = 0.75');
    expect(dashboard).not.toContain('score_r ?? 0');
    expect(dashboard).not.toContain('R = 0.40·D');
    expect(dashboard).not.toContain('correlation_window_seconds || 20');
    expect(dashboard).toContain('THRESHOLD NOT REPORTED');
  });

  it('names missing geolocation explicitly', () => {
    expect(read('../src/pages/Map.jsx')).toContain('NO REGISTERED CAMERA LOCATION');
    expect(read('../src/components/TacticalMap.jsx')).toContain('NO REGISTERED CAMERA LOCATION');
  });

  it('wires alert collection and per-alert labels to explicit truth helpers', () => {
    const alerts = read('../src/pages/Alerts.jsx');
    expect(alerts).toContain('alertsPageSubtitle(capabilities)');
    expect(alerts).toContain('totalRecordedAlerts(realAlerts)');
    expect(alerts).toContain('isCrossCommandEscalation(alert)');
    expect(alerts).toContain('isCorroboratedAlert(alert)');
    expect(alerts).not.toContain('Cross-command escalated events');
  });
});
