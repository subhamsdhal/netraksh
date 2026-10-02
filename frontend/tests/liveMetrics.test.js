import { describe, expect, it } from 'vitest';
import { deriveGlobalEdgeStatus, processingFpsForTelemetry, sourceFpsForTelemetry, startupEdgeReadiness } from '../src/utils/liveMetrics';

const now = 1_000_000;
const live = { timestamp: now - 100, processing_fps: 0.24, source_fps: 29.97 };

describe('live dashboard metrics', () => {
  it('promotes fresh telemetry over stale waking intent', () => {
    expect(deriveGlobalEdgeStatus({ analysisStates: [{ intent: 'WAKING', hasFreshCurrentTelemetry: true }], lastTelemetryAt: now - 100, edgeWakeUntil: now + 10_000, now })).toBe('ONLINE');
  });

  it('reports idle after completed processing with no active intent', () => {
    expect(deriveGlobalEdgeStatus({ analysisStates: [{ intent: 'IDLE' }], lastTelemetryAt: now - 60_000, now })).toBe('IDLE');
  });

  it('reports passive worker readiness without claiming active analysis', () => {
    expect(deriveGlobalEdgeStatus({
      analysisStates: [{ cameraId: 'cam-border-01', intent: 'IDLE' }],
      prewarm: { eligible: 2, warming: 0, ready: 2 },
      now,
    })).toBe('READY');
  });

  it('prioritizes current-run telemetry over passive prewarm readiness', () => {
    expect(deriveGlobalEdgeStatus({
      analysisStates: [{ cameraId: 'cam-border-01', intent: 'ACTIVE', hasFreshCurrentTelemetry: true }],
      lastTelemetryAt: now - 100,
      prewarm: { eligible: 2, warming: 0, ready: 2 },
      now,
    })).toBe('ONLINE');
  });

  it('reports an exhausted prewarm as unavailable rather than idle or ready', () => {
    expect(deriveGlobalEdgeStatus({
      analysisStates: [{ intent: 'IDLE' }],
      prewarm: { eligible: 2, warming: 0, ready: 0, terminal: 2 },
      now,
    })).toBe('UNAVAILABLE');
  });

  it('lets authoritative ready state replace the initial startup-warming hint', () => {
    expect(deriveGlobalEdgeStatus({
      analysisStates: [{ intent: 'IDLE' }],
      startupWakeRequested: true,
      prewarm: { eligible: 2, warming: 0, ready: 2, terminal: 0 },
      now,
    })).toBe('READY');
  });

  it('uses the authoritative startup snapshot without an optional prewarm event', () => {
    const startup = {
      requested: true,
      camBorder01: { status: 'READY' },
      camCheckpoint01: { status: 'READY' },
    };
    expect(deriveGlobalEdgeStatus({ startup, now })).toBe('READY');
    expect(startupEdgeReadiness(startup)).toMatchObject({ eligible: 2, ready: 2 });
  });

  it('keeps two configured edges in the denominator while startup is warming', () => {
    const startup = {
      requested: true,
      camBorder01: { status: 'WAKING' },
      camCheckpoint01: { status: 'WAKING' },
    };
    expect(deriveGlobalEdgeStatus({ startup, now })).toBe('WARMING');
    expect(startupEdgeReadiness(startup)).toMatchObject({ eligible: 2, ready: 0 });
  });

  it('distinguishes background revalidation from initial warming', () => {
    const startup = {
      requested: true,
      revalidating: true,
      lastReadyEdgeCount: 2,
      camBorder01: { status: 'WAKING' },
      camCheckpoint01: { status: 'WAKING' },
    };
    expect(deriveGlobalEdgeStatus({ startup, now })).toBe('RECHECKING');
    expect(startupEdgeReadiness(startup)).toMatchObject({ eligible: 2, ready: 0, lastReady: 2 });
  });

  it('reports current partial progress during revalidation', () => {
    const startup = {
      requested: true,
      revalidating: true,
      lastReadyEdgeCount: 2,
      camBorder01: { status: 'READY' },
      camCheckpoint01: { status: 'WAKING' },
    };
    expect(deriveGlobalEdgeStatus({ startup, now })).toBe('RECHECKING');
    expect(startupEdgeReadiness(startup)).toMatchObject({ eligible: 2, ready: 1 });
  });

  it('uses processing throughput, not pipeline metric or source FPS, for AI FPS', () => {
    expect(processingFpsForTelemetry(live, now)).toBe(0.24);
    expect(processingFpsForTelemetry({ ...live, processing_fps: 0.24, source_fps: 24 }, now)).not.toBe(24);
  });

  it('uses measured source metadata and never copies processing FPS', () => {
    expect(sourceFpsForTelemetry(live)).toBe(29.97);
    expect(sourceFpsForTelemetry({ processing_fps: 0.24 })).toBeNull();
  });

  it('does not present completed historical processing as current', () => {
    expect(processingFpsForTelemetry({ ...live, analysis_state: 'COMPLETED' }, now)).toBeNull();
  });

  it('does not let another camera intent alter the selected camera calculation', () => {
    expect(deriveGlobalEdgeStatus({ analysisStates: [{ cameraId: 'cam-border-01', intent: 'ACTIVE', hasFreshCurrentTelemetry: true }], lastTelemetryAt: now - 100, now })).toBe('ONLINE');
  });
});
