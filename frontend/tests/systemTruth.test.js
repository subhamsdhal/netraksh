import { describe, expect, it } from 'vitest';
import {
  cameraHealthPresentation,
  capabilityLabel,
  deriveCameraOperationalState,
  deriveSystemStatus,
  deriveSyncState,
  formatTelemetryAge,
} from '../src/utils/systemTruth';

describe('production truth state derivation', () => {
  it('does not call the control plane offline while HTTP or WebSocket proves availability', () => {
    expect(deriveSystemStatus({ backendHealthy: false, lastBackendHealthyAt: 0, isWsConnected: true, now: 100_000 })).toBe('OPERATIONAL');
    expect(deriveSystemStatus({ backendHealthy: false, lastBackendHealthyAt: 90_000, isWsConnected: false, now: 100_000 })).toBe('OPERATIONAL');
    expect(deriveSystemStatus({ backendHealthy: false, lastBackendHealthyAt: 1, isWsConnected: false, now: 100_000 })).toBe('OFFLINE');
  });
  it('never calls a zero-activity queue current', () => {
    expect(deriveSyncState({ isConnected: true, queued: 0, failed: 0, hasActivity: false })).toBe('IDLE');
    expect(deriveSyncState({ isConnected: true, queued: 0, failed: 0, hasActivity: true })).toBe('CURRENT');
    expect(deriveSyncState({ isConnected: true, queued: 2 })).toBe('BUFFERING');
    expect(deriveSyncState({ isConnected: true, failed: 1 })).toBe('FAILED');
    expect(deriveSyncState({ isConnected: false })).toBe('DISCONNECTED');
  });

  it('separates ready worker, missing source, idle analysis, and absent telemetry', () => {
    expect(deriveCameraOperationalState({ nodeStatus: 'READY', sourceState: null, telemetry: null })).toEqual({
      node: 'READY', source: 'NOT LOADED', analysis: 'IDLE', telemetry: 'NONE',
    });
    expect(deriveCameraOperationalState({ nodeStatus: 'READY', telemetry: { timestamp: 1000 }, now: 1010_000 }).analysis).toBe('LIVE');
  });

  it('does not claim an unreported capability', () => {
    expect(capabilityLabel(undefined, 'AVAILABLE')).toBe('NOT REPORTED');
    expect(capabilityLabel(false, 'AVAILABLE', 'UNAVAILABLE')).toBe('UNAVAILABLE');
  });

  it('distinguishes fresh, stale, and missing camera health independently of worker readiness', () => {
    const now = Date.parse('2026-10-02T12:00:00Z');
    expect(cameraHealthPresentation({
      health_state: 'OK', health_reason: 'healthy', fps_actual: 24,
      last_health_check: '2026-10-02T11:59:50Z',
    }, now)).toMatchObject({ health: 'OK', fps: '24.00', stale: false });
    expect(cameraHealthPresentation({
      health_state: 'DEGRADED', health_reason: 'fps_degraded', fps_actual: 4,
      last_health_check: '2026-10-02T11:58:00Z',
    }, now)).toMatchObject({
      health: 'STALE · LAST MEASURED DEGRADED',
      fps: 'N/A CURRENT',
      reason: 'Last measured: fps_degraded',
      stale: true,
    });
    expect(cameraHealthPresentation({}, now)).toEqual({
      health: 'NOT REPORTED', fps: 'N/A', reason: 'N/A', sample: 'Never', stale: false,
    });

    const worker = deriveCameraOperationalState({ nodeStatus: 'READY', telemetry: null, now });
    const staleHealth = cameraHealthPresentation({
      health_state: 'OK', last_health_check: '2026-10-02T11:58:00Z',
    }, now);
    expect(worker.node).toBe('READY');
    expect(staleHealth.stale).toBe(true);
  });

  it('formats telemetry age concisely from seconds through days', () => {
    expect(formatTelemetryAge(12_900)).toBe('12s ago');
    expect(formatTelemetryAge(8 * 60_000)).toBe('8m ago');
    expect(formatTelemetryAge(15 * 3_600_000)).toBe('15h ago');
    expect(formatTelemetryAge(2 * 86_400_000)).toBe('2d ago');
  });
});
