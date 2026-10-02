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

  it('uses shared freshness and age truth in the command center', () => {
    const dashboard = read('../src/pages/Dashboard.jsx');
    expect(dashboard).toContain('cameraHealthPresentation(health[activeCameraId], now)');
    expect(dashboard).toContain('formatTelemetryAge(telemetryAgeMs)');
    expect(dashboard).not.toContain('telemetryAgeMs / 1000).toFixed(1)');
  });

  it('names missing geolocation explicitly', () => {
    expect(read('../src/pages/Map.jsx')).toContain('NO REGISTERED CAMERA LOCATION');
    expect(read('../src/components/TacticalMap.jsx')).toContain('NO REGISTERED CAMERA LOCATION');
  });
});
