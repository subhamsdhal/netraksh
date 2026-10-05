import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import VideoFeed from '../src/components/VideoFeed';
import { authFetch } from '../src/services/auth';

vi.mock('../src/services/auth', () => ({ authFetch: vi.fn() }));

describe('per-camera authoritative analyzed frame', () => {
  beforeEach(() => {
    global.ResizeObserver = class { observe() {} disconnect() {} };
    URL.createObjectURL = vi.fn(() => 'blob:analyzed-frame');
    URL.revokeObjectURL = vi.fn();
    global.Image = class {
      set src(_value) { queueMicrotask(() => this.onload?.()); }
    };
    HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
    HTMLMediaElement.prototype.pause = vi.fn();
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({
      setTransform: vi.fn(), clearRect: vi.fn(), fillRect: vi.fn(), strokeRect: vi.fn(),
      fillText: vi.fn(), measureText: vi.fn(() => ({ width: 40 })),
    }));
    const headers = new Headers({
      'X-Analysis-Session': 'session-1', 'X-Frame-Index': '42',
      'X-Person-Count': '1', 'X-Vehicle-Count': '1', 'X-Track-Count': '2',
    });
    authFetch.mockResolvedValue({ ok: true, headers, blob: async () => new Blob(['jpeg']) });
  });

  it('plays durable uploads at 1.0x and promotes the image-grounded tracking canvas', async () => {
    const { container } = render(<VideoFeed
      cameraId="cam-border-01"
      mediaUrl="blob:video"
      sourceMode="durable"
      expectedSessionId="session-1"
      telemetryStatus="LIVE"
      liveTracksData={{
        camera_id: 'cam-border-01',
        stream_id: 'session-1',
        analysis_session_id: 'session-1', frame_index: 42, preview_available: true,
        person_count: 1, vehicle_count: 1, track_count: 2, tracks: [],
        frame_width: 768, frame_height: 576,
      }}
    />);

    const video = container.querySelector('video');
    expect(video).toBeInTheDocument();
    Object.defineProperty(video, 'playbackRate', { value: 1, writable: true });
    window.dispatchEvent(new CustomEvent('netraksh-tracking-frame', { detail: {
      camera_id: 'cam-border-01', stream_id: 'session-1', analysis_session_id: 'run-1',
      analysis_generation: null, frame_index: 42, video_time: 0.5, tracks: [],
    } }));
    await waitFor(() => expect(screen.getByLabelText('Current source-frame tracking overlay')).toHaveStyle({ display: 'block' }));
    expect(video.playbackRate).toBe(1);
    expect(screen.getByText(/SOURCE PLAYBACK 1.0×/)).toBeInTheDocument();
  });

  it('corrects live source playback when it outruns authoritative HUD time', async () => {
    const { container } = render(<VideoFeed
      cameraId="cam-checkpoint-01"
      mediaUrl="blob:video"
      sourceMode="durable"
      expectedSessionId="source-1"
      expectedGeneration={1}
      telemetryStatus="LIVE"
      liveTracksData={{
        camera_id: 'cam-checkpoint-01', stream_id: 'source-1',
        analysis_session_id: 'run-1', analysis_generation: 1,
        frame_index: 42, video_time: 6.38, preview_available: true,
      }}
    />);
    const video = container.querySelector('video');
    Object.defineProperty(video, 'currentTime', { value: 10, writable: true });
    Object.defineProperty(video, 'playbackRate', { value: 1, writable: true });

    window.dispatchEvent(new CustomEvent('netraksh-tracking-frame', { detail: {
      camera_id: 'cam-checkpoint-01', stream_id: 'source-1', analysis_session_id: 'run-1',
      analysis_generation: 1, frame_index: 42, video_time: 6.38, tracks: [],
    } }));

    await waitFor(() => expect(video.currentTime).toBeCloseTo(6.34, 5));
    expect(video.playbackRate).toBe(1);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();

    HTMLMediaElement.prototype.play.mockClear();
    video.currentTime = 7;
    window.dispatchEvent(new CustomEvent('netraksh-tracking-frame', { detail: {
      camera_id: 'cam-checkpoint-01', stream_id: 'source-1', analysis_session_id: 'run-1',
      analysis_generation: 1, frame_index: 8, video_time: 1, tracks: [],
    } }));
    await waitFor(() => expect(video.currentTime).toBeCloseTo(6.34, 5));
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
  });

  it('does not fetch a frame for a stale session', async () => {
    render(<VideoFeed
      cameraId="cam-border-01"
      mediaUrl="blob:video"
      sourceMode="durable"
      expectedSessionId="new-session"
      telemetryStatus="LIVE"
      liveTracksData={{ stream_id: 'old-session', analysis_session_id: 'old-session', frame_index: 42, preview_available: true }}
    />);
    expect(authFetch).not.toHaveBeenCalled();
    expect(screen.getByText(/SOURCE PREVIEW · WAITING FOR FIRST ANALYZED FRAME/)).toBeInTheDocument();
    expect(screen.queryByText(/ANALYZED FRAME UNAVAILABLE/i)).not.toBeInTheDocument();
    expect(screen.getByTitle('WAITING FOR HUD')).toBeDisabled();
  });

  it('does not offer an add-source action while durable authority is restoring', () => {
    render(<VideoFeed
      cameraId="cam-border-01"
      sourceRestoring
      sourceRunState="RESTORING"
      canUpload
    />);
    expect(screen.getByText('RESTORING STORED SOURCE...')).toBeInTheDocument();
    expect(screen.queryByText('ADD VIDEO SOURCE')).not.toBeInTheDocument();
  });

  it('never calls an authoritative stored source NO VIDEO SOURCE when preview transport is absent', () => {
    render(<VideoFeed
      cameraId="cam-checkpoint-01"
      sourceMode="durable"
      sourceRunState="PAUSED"
      expectedSessionId="stored-source"
      telemetryStatus="STALE"
      canUpload
    />);
    expect(screen.getByText('SOURCE STORED · PREVIEW UNAVAILABLE FOR RESTORED SESSION')).toBeInTheDocument();
    expect(screen.queryByText('NO VIDEO SOURCE')).not.toBeInTheDocument();
    expect(screen.queryByText('ADD VIDEO SOURCE')).not.toBeInTheDocument();
  });

  it('shows measured upload progress and never claims normalization before it is known', () => {
    render(<VideoFeed
      cameraId="cam-checkpoint-01"
      isUploading
      uploadStage="UPLOADING"
      uploadProgress={63}
      canUpload
      sourceMode="durable"
      sourceRunState="UPLOADING"
    />);
    expect(screen.getByText('UPLOADING 63%')).toBeInTheDocument();
    expect(screen.queryByText(/NORMALIZING/)).not.toBeInTheDocument();
  });

  it('keeps preview availability separate from source readiness', () => {
    render(<VideoFeed
      cameraId="cam-checkpoint-01"
      sourceMode="durable"
      sourceRunState="READY"
      expectedSessionId="ready-source"
      telemetryStatus="WAITING"
      canUpload
    />);
    expect(screen.getByText('SOURCE STORED · PREVIEW UNAVAILABLE FOR RESTORED SESSION')).toBeInTheDocument();
    expect(screen.queryByText(/UPLOADING/)).not.toBeInTheDocument();
  });

  it('names an active restored source as awaiting its current analyzed frame', () => {
    render(<VideoFeed
      cameraId="cam-checkpoint-01"
      sourceMode="durable"
      sourceRunState="LIVE"
      expectedSessionId="stored-source"
      telemetryStatus="OFFLINE"
      canUpload
    />);
    expect(screen.getByText('SOURCE STORED · AWAITING CURRENT-RUN ANALYZED FRAME')).toBeInTheDocument();
    expect(screen.queryByText('SOURCE STORED · PREVIEW UNAVAILABLE FOR RESTORED SESSION')).not.toBeInTheDocument();
  });

  it('labels persisted completed telemetry as historical rather than active', () => {
    render(<VideoFeed
      cameraId="cam-border-01"
      sourceMode="durable"
      sourceRunState="COMPLETED"
      expectedSessionId="session-1"
      telemetryStatus="COMPLETED"
      liveTracksData={{ analysis_session_id: 'session-1', frame_index: 42 }}
    />);
    expect(screen.getByText('SOURCE STORED · ANALYSIS COMPLETED')).toBeInTheDocument();
    expect(screen.queryByText('TELEMETRY ACTIVE · LOCAL PLAYBACK OPTIONAL')).not.toBeInTheDocument();
  });

  it('does not say a completed source is waiting for its first analyzed frame', () => {
    render(<VideoFeed
      cameraId="cam-border-01"
      mediaUrl="blob:video"
      sourceMode="durable"
      sourceRunState="COMPLETED"
      expectedSessionId="source-1"
      telemetryStatus="COMPLETED"
      liveTracksData={{ stream_id: 'source-1', analysis_session_id: 'run-1', frame_index: 42, preview_available: false }}
    />);
    expect(screen.getByText('SOURCE REPLAY · HUD NOT AVAILABLE FOR THIS HISTORICAL RUN')).toBeInTheDocument();
    expect(screen.queryByText('SOURCE PREVIEW · WAITING FOR FIRST ANALYZED FRAME')).not.toBeInTheDocument();
    expect(screen.queryByText(/ANALYZED FRAME UNAVAILABLE/i)).not.toBeInTheDocument();
    expect(screen.getByText('HUD UNAVAILABLE')).toBeDisabled();
  });

  it('settles completed replay loading to an explicit unavailable state', () => {
    const props = {
      cameraId: 'cam-border-01', mediaUrl: 'blob:video', sourceMode: 'durable',
      sourceRunState: 'COMPLETED', expectedSessionId: 'source-1', telemetryStatus: 'COMPLETED',
      completedSummary: {
        camera_id: 'cam-border-01', stream_id: 'source-1', analysis_session_id: 'run-1',
        analysis_generation: 1, final_video_time: 10,
      },
    };
    const { rerender } = render(<VideoFeed {...props} completedSummaryLoading />);
    expect(screen.getByText('LOADING HUD')).toBeInTheDocument();
    rerender(<VideoFeed {...props} completedSummaryLoading={false} completedTimeline={[]} />);
    expect(screen.getByText('HUD UNAVAILABLE')).toBeInTheDocument();
    expect(screen.queryByText('ANALYZED VIEW PENDING')).not.toBeInTheDocument();
  });

  it('restores a completed analyzed timeline for replay without starting a new analysis', async () => {
    const completedTimeline = [{
      camera_id: 'cam-checkpoint-01', stream_id: 'source-2', analysis_session_id: 'run-2',
      analysis_generation: 1, source_generation: 9, sequence: 4, frame_index: 12,
      video_time: 0.5, frame_width: 640, frame_height: 360,
      person_count: 1, vehicle_count: 0, track_count: 1, tracks: [],
    }];
    render(<VideoFeed
      cameraId="cam-checkpoint-01"
      mediaUrl="blob:video"
      sourceMode="durable"
      sourceRunState="COMPLETED"
      expectedSessionId="source-2"
      expectedGeneration={1}
      expectedSourceGeneration={9}
      telemetryStatus="COMPLETED"
      completedTimeline={completedTimeline}
      completedSummary={{
        camera_id: 'cam-checkpoint-01', stream_id: 'source-2', analysis_session_id: 'run-2',
        analysis_generation: 1, source_generation: 9, final_video_time: 0.5,
      }}
    />);
    await waitFor(() => expect(screen.getByText(/COMPLETED RUN · ANALYZED REPLAY/)).toBeInTheDocument());
    expect(screen.getByText('ANALYZED REPLAY')).toBeInTheDocument();
    expect(screen.getByLabelText('Current source-frame tracking overlay')).toHaveStyle({ display: 'block' });
  });

  it('promotes the first exact frame once, respects source preview, and resets for the next run', async () => {
    authFetch.mockImplementation(async (url) => {
      const params = new URL(url, 'https://example.test').searchParams;
      const session = params.get('analysis_session_id');
      const frame = params.get('frame_index');
      return {
        ok: true,
        headers: new Headers({
          'X-Analysis-Session': session,
          'X-Frame-Index': frame,
          'X-Person-Count': '1', 'X-Vehicle-Count': '0', 'X-Track-Count': '1',
        }),
        blob: async () => new Blob(['jpeg']),
      };
    });
    const sample = (run, frame) => ({
      camera_id: 'cam-checkpoint-01', stream_id: 'source-1', analysis_session_id: run,
      analysis_generation: run === 'run-1' ? 1 : 2, frame_index: frame, preview_available: true,
      person_count: 1, vehicle_count: 0, track_count: 1,
      tracks: [{ track_id: 7, class_name: 'person', bbox_x: 0.1, bbox_y: 0.1, bbox_w: 0.2, bbox_h: 0.4 }],
      frame_width: 960, frame_height: 540,
    });
    const { rerender, container } = render(<VideoFeed
      cameraId="cam-checkpoint-01" mediaUrl="blob:video" sourceMode="durable"
      expectedSessionId="source-1" expectedGeneration={1} telemetryStatus="LIVE"
      liveTracksData={sample('run-1', 1)}
    />);
    await waitFor(() => expect(screen.getByTitle('Show source preview')).toHaveAttribute('aria-pressed', 'true'));
    expect(container.querySelector('[data-track-id="7"][data-track-class="person"]')).not.toBeNull();
    expect(screen.getByText((content) => content.includes('PERSONS 1') && content.includes('VEHICLES 0') && content.includes('TRACKS 1'))).toBeInTheDocument();

    screen.getByTitle('Show source preview').click();
    await waitFor(() => expect(screen.getByTitle('Show analyzed HUD')).toHaveAttribute('aria-pressed', 'false'));
    rerender(<VideoFeed
      cameraId="cam-checkpoint-01" mediaUrl="blob:video" sourceMode="durable"
      expectedSessionId="source-1" expectedGeneration={1} telemetryStatus="LIVE"
      liveTracksData={sample('run-1', 2)}
    />);
    await waitFor(() => expect(authFetch).toHaveBeenCalledTimes(2));
    expect(screen.getByTitle('Show analyzed HUD')).toHaveAttribute('aria-pressed', 'false');

    rerender(<VideoFeed
      cameraId="cam-checkpoint-01" mediaUrl="blob:video" sourceMode="durable"
      expectedSessionId="source-1" expectedGeneration={2} telemetryStatus="LIVE"
      liveTracksData={sample('run-2', 1)}
    />);
    await waitFor(() => expect(screen.getByTitle('Show source preview')).toHaveAttribute('aria-pressed', 'true'));
  });

  it('rejects wrong-camera and stale-generation frames before analyzed-view promotion', () => {
    const { rerender } = render(<VideoFeed
      cameraId="cam-checkpoint-01" mediaUrl="blob:video" sourceMode="durable"
      expectedSessionId="source-1" expectedGeneration={3} telemetryStatus="LIVE"
      liveTracksData={{
        camera_id: 'cam-border-01', stream_id: 'source-1', analysis_session_id: 'run-1',
        analysis_generation: 3, frame_index: 1, preview_available: true,
      }}
    />);
    expect(authFetch).not.toHaveBeenCalled();
    rerender(<VideoFeed
      cameraId="cam-checkpoint-01" mediaUrl="blob:video" sourceMode="durable"
      expectedSessionId="source-1" expectedGeneration={3} telemetryStatus="LIVE"
      liveTracksData={{
        camera_id: 'cam-checkpoint-01', stream_id: 'source-1', analysis_session_id: 'run-1',
        analysis_generation: 2, frame_index: 1, preview_available: true,
      }}
    />);
    expect(authFetch).not.toHaveBeenCalled();
    expect(screen.getByText('WAITING FOR HUD')).toBeInTheDocument();
  });

  it('renders authoritative person and vehicle boxes with the same-frame counts', async () => {
    const telemetry = {
      camera_id: 'cam-checkpoint-01', stream_id: 'source-1', analysis_session_id: 'session-1',
      analysis_generation: 4, frame_index: 42, preview_available: true,
      person_count: 1, vehicle_count: 1, track_count: 2,
      tracks: [
        { track_id: 11, class_name: 'person', bbox_x: 0.1, bbox_y: 0.1, bbox_w: 0.2, bbox_h: 0.4 },
        { track_id: 12, class_name: 'car', bbox_x: 0.5, bbox_y: 0.4, bbox_w: 0.3, bbox_h: 0.25 },
      ],
      frame_width: 960, frame_height: 540,
    };
    const { container } = render(<VideoFeed
      cameraId="cam-checkpoint-01" mediaUrl="blob:video" sourceMode="durable"
      expectedSessionId="source-1" expectedGeneration={4} telemetryStatus="LIVE" liveTracksData={telemetry}
    />);
    await waitFor(() => expect(screen.getByTitle('Show source preview')).toHaveAttribute('aria-pressed', 'true'));
    expect(container.querySelector('[data-track-id="11"][data-track-class="person"]')).not.toBeNull();
    expect(container.querySelector('[data-track-id="12"][data-track-class="car"]')).not.toBeNull();
    expect(screen.getByText((content) => content.includes('PERSONS 1') && content.includes('VEHICLES 1') && content.includes('TRACKS 2'))).toBeInTheDocument();
  });

  it('moves a box only when the next exact authoritative frame commits', async () => {
    const onAnalyzedSample = vi.fn();
    authFetch.mockImplementation(async (url) => {
      const params = new URL(url, 'https://example.test').searchParams;
      return {
        ok: true,
        headers: new Headers({
          'X-Analysis-Session': params.get('analysis_session_id'),
          'X-Frame-Index': params.get('frame_index'),
          'X-Person-Count': '1', 'X-Vehicle-Count': '0', 'X-Track-Count': '1',
        }),
        blob: async () => new Blob(['jpeg']),
      };
    });
    const frame = (frameIndex, bboxX) => ({
      camera_id: 'cam-checkpoint-01', stream_id: 'source-1', analysis_session_id: 'run-1',
      analysis_generation: 1, sequence: frameIndex, frame_index: frameIndex,
      video_time: frameIndex / 24, preview_available: true,
      person_count: 1, vehicle_count: 0, track_count: 1,
      tracks: [{ track_id: 7, class_name: 'person', bbox_x: bboxX, bbox_y: 0.1, bbox_w: 0.2, bbox_h: 0.4 }],
      frame_width: 960, frame_height: 540,
    });
    const { container, rerender } = render(<VideoFeed
      cameraId="cam-checkpoint-01" mediaUrl="blob:video" sourceMode="durable"
      expectedSessionId="source-1" expectedGeneration={1} telemetryStatus="LIVE"
      liveTracksData={frame(10, 0.1)} onAnalyzedSample={onAnalyzedSample}
    />);
    await waitFor(() => expect(container.querySelector('[data-track-id="7"]')).toHaveAttribute('data-bbox-x', '0.1'));
    await waitFor(() => expect(onAnalyzedSample).toHaveBeenLastCalledWith(expect.objectContaining({ frame_index: 10 })));

    rerender(<VideoFeed
      cameraId="cam-checkpoint-01" mediaUrl="blob:video" sourceMode="durable"
      expectedSessionId="source-1" expectedGeneration={1} telemetryStatus="LIVE"
      liveTracksData={frame(11, 0.35)} onAnalyzedSample={onAnalyzedSample}
    />);
    await waitFor(() => expect(container.querySelector('[data-track-id="7"]')).toHaveAttribute('data-bbox-x', '0.35'));
    expect(onAnalyzedSample).toHaveBeenLastCalledWith(expect.objectContaining({ frame_index: 11, video_time: 11 / 24 }));
  });

  it('does not mislabel one final analyzed frame as a completed replay timeline', async () => {
    const telemetry = {
      camera_id: 'cam-checkpoint-01', stream_id: 'source-1', analysis_session_id: 'session-1',
      analysis_generation: 1, frame_index: 42, preview_available: true,
      person_count: 1, vehicle_count: 1, track_count: 2, tracks: [], frame_width: 960, frame_height: 540,
    };
    const { rerender } = render(<VideoFeed
      cameraId="cam-checkpoint-01" mediaUrl="blob:video" sourceMode="durable"
      expectedSessionId="source-1" expectedGeneration={1} telemetryStatus="LIVE" liveTracksData={telemetry}
    />);
    await waitFor(() => expect(screen.getByTitle('Show source preview')).toHaveAttribute('aria-pressed', 'true'));
    rerender(<VideoFeed
      cameraId="cam-checkpoint-01" mediaUrl="blob:video" sourceMode="durable"
      expectedSessionId="source-1" expectedGeneration={1} sourceRunState="COMPLETED"
      telemetryStatus="COMPLETED" liveTracksData={telemetry}
    />);
    expect(screen.getByText('HUD UNAVAILABLE')).toHaveAttribute('data-view-state', 'COMPLETED_REPLAY_UNAVAILABLE');
    expect(screen.queryByAltText('Synchronized analyzed video frame for cam-checkpoint-01')).not.toBeInTheDocument();
  });

  it('uses the active label only for live telemetry', () => {
    const { rerender } = render(<VideoFeed
      cameraId="cam-border-01"
      telemetryStatus="LIVE"
      liveTracksData={{ analysis_session_id: 'session-1', frame_index: 42 }}
    />);
    expect(screen.getByText('TELEMETRY ACTIVE · LOCAL PLAYBACK OPTIONAL')).toBeInTheDocument();

    rerender(<VideoFeed
      cameraId="cam-border-01"
      telemetryStatus="STALE"
      liveTracksData={{ analysis_session_id: 'session-1', frame_index: 42 }}
    />);
    expect(screen.getByText('LAST TELEMETRY AVAILABLE · NOT LIVE')).toBeInTheDocument();
    expect(screen.queryByText('TELEMETRY ACTIVE · LOCAL PLAYBACK OPTIONAL')).not.toBeInTheDocument();
  });
});
