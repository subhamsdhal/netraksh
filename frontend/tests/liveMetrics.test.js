import { describe, expect, it } from 'vitest';
import { deriveGlobalEdgeStatus, processingFpsForTelemetry, sourceFpsForTelemetry } from '../src/utils/liveMetrics';

const now = 1_000_000;
const live = { timestamp: now - 100, processing_fps: 0.24, source_fps: 29.97 };

describe('live dashboard metrics', () => {
  it('promotes fresh telemetry over stale waking intent', () => {
    expect(deriveGlobalEdgeStatus({ analysisStates: [{ intent: 'WAKING', hasFreshCurrentTelemetry: true }], lastTelemetryAt: now - 100, edgeWakeUntil: now + 10_000, now })).toBe('ONLINE');
  });

  it('reports idle after completed processing with no active intent', () => {
    expect(deriveGlobalEdgeStatus({ analysisStates: [{ intent: 'IDLE' }], lastTelemetryAt: now - 60_000, now })).toBe('IDLE');
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
