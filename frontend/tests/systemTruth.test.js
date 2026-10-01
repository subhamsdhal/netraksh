import { describe, expect, it } from 'vitest';
import { capabilityLabel, deriveCameraOperationalState, deriveSyncState } from '../src/utils/systemTruth';

describe('production truth state derivation', () => {
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
});
