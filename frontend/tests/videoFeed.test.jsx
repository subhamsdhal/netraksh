import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import VideoFeed from '../src/components/VideoFeed';

const scope = {
  camera_id: 'cam-checkpoint-01',
  stream_id: 'source-1',
  analysis_session_id: 'run-1',
  analysis_generation: 2,
  source_generation: 3,
};

const track = (overrides = {}) => ({
  track_id: 9,
  class_name: 'person',
  detection_class: 'person',
  detector_confirmed: true,
  confidence: 0.88,
  bbox_x: 0.2,
  bbox_y: 0.15,
  bbox_w: 0.25,
  bbox_h: 0.5,
  ...overrides,
});

const sample = (overrides = {}) => ({
  ...scope,
  sequence: 1,
  frame_index: 12,
  video_time: 0.4,
  frame_width: 1280,
  frame_height: 720,
  bbox_format: 'XYWH',
  coordinate_space: 'NORMALIZED_FRAME',
  detection_method: 'YOLO_BYTE_TRACK',
  person_count: 1,
  vehicle_count: 0,
  track_count: 1,
  tracks: [track()],
  ...overrides,
});

function wireVideo(video) {
  let time = 0;
  Object.defineProperty(video, 'currentTime', {
    configurable: true,
    get: () => time,
    set: (value) => {
      time = Number(value);
      queueMicrotask(() => video.dispatchEvent(new Event('seeked')));
    },
  });
  Object.defineProperty(video, 'readyState', { configurable: true, value: 4 });
  Object.defineProperty(video, 'videoWidth', { configurable: true, value: 1280 });
  Object.defineProperty(video, 'videoHeight', { configurable: true, value: 720 });
  return video;
}

const renderFeed = (props = {}) => render(<VideoFeed
  cameraId="cam-checkpoint-01"
  mediaUrl="blob:video"
  sourceMode="durable"
  expectedSessionId="source-1"
  expectedGeneration={2}
  expectedSourceGeneration={3}
  telemetryStatus="LIVE"
  {...props}
/>);

describe('detection-synchronized analyzed playback', () => {
  beforeEach(() => {
    global.ResizeObserver = class { observe() {} disconnect() {} };
    global.requestAnimationFrame = callback => setTimeout(() => callback(performance.now()), 0);
    global.cancelAnimationFrame = clearTimeout;
    HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
    HTMLMediaElement.prototype.pause = vi.fn();
    HTMLMediaElement.prototype.requestVideoFrameCallback = vi.fn(function requestFrame(callback) {
      queueMicrotask(() => callback(performance.now(), { mediaTime: this.currentTime }));
      return 1;
    });
    HTMLMediaElement.prototype.cancelVideoFrameCallback = vi.fn();
  });

  it('defaults durable media to ANALYZED SYNC without starting browser playback', () => {
    const { container } = renderFeed();
    const video = wireVideo(container.querySelector('video'));
    fireEvent.loadedMetadata(video);
    expect(screen.getByTitle('View source preview')).toHaveAttribute('data-playback-mode', 'analyzed-sync');
    expect(video).not.toHaveAttribute('controls');
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it('seeks to a detector-confirmed sample and atomically commits frame, boxes and metrics', async () => {
    const onAnalyzedSample = vi.fn();
    const { container } = renderFeed({ onAnalyzedSample });
    const video = wireVideo(container.querySelector('video'));
    act(() => window.dispatchEvent(new CustomEvent('netraksh-tracking-frame', { detail: sample() })));

    await waitFor(() => expect(onAnalyzedSample).toHaveBeenLastCalledWith(expect.objectContaining({
      frame_index: 12, video_time: 0.4, person_count: 1, track_count: 1,
    })));
    expect(video.currentTime).toBeCloseTo(0.4, 5);
    expect(screen.getByLabelText('Detection-synchronized tracking overlay')).toHaveAttribute('data-frame-index', '12');
    expect(container.querySelector('[data-track-id="9"][data-track-class="person"]')).toBeInTheDocument();
    expect(screen.getByText('FRAME 12 · 0.40s')).toBeInTheDocument();
  });

  it('presents a paused seek when requestVideoFrameCallback never fires', async () => {
    HTMLMediaElement.prototype.requestVideoFrameCallback = vi.fn(() => 1);
    const onAnalyzedSample = vi.fn();
    const { container } = renderFeed({ onAnalyzedSample });
    const video = wireVideo(container.querySelector('video'));
    act(() => window.dispatchEvent(new CustomEvent('netraksh-tracking-frame', { detail: sample() })));
    await waitFor(() => expect(onAnalyzedSample).toHaveBeenLastCalledWith(expect.objectContaining({ frame_index: 12 })), { timeout: 1500 });
    expect(video.currentTime).toBeCloseTo(0.4, 5);
    expect(container.querySelector('[data-track-id="9"]')).toBeInTheDocument();
  });

  it('falls back when requestVideoFrameCallback reports the previous painted frame', async () => {
    HTMLMediaElement.prototype.requestVideoFrameCallback = vi.fn((callback) => {
      queueMicrotask(() => callback(performance.now(), { mediaTime: 0 }));
      return 1;
    });
    const onAnalyzedSample = vi.fn();
    const { container } = renderFeed({ onAnalyzedSample });
    const video = wireVideo(container.querySelector('video'));
    act(() => window.dispatchEvent(new CustomEvent('netraksh-tracking-frame', { detail: sample() })));
    await waitFor(() => expect(onAnalyzedSample).toHaveBeenLastCalledWith(expect.objectContaining({ frame_index: 12 })), { timeout: 1500 });
    expect(video.currentTime).toBeCloseTo(0.4, 5);
    expect(container.querySelector('[data-track-id="9"]')).toBeInTheDocument();
  });

  it('rejects optical-flow-only and malformed boxes instead of displaying irregular HUD data', async () => {
    const onAnalyzedSample = vi.fn();
    const { container } = renderFeed({ onAnalyzedSample });
    wireVideo(container.querySelector('video'));
    act(() => {
      window.dispatchEvent(new CustomEvent('netraksh-tracking-frame', {
        detail: sample({ detection_method: 'OPTICAL_FLOW' }),
      }));
      window.dispatchEvent(new CustomEvent('netraksh-tracking-frame', {
        detail: sample({ frame_index: 13, tracks: [track({ bbox_w: -0.2 })] }),
      }));
    });
    await new Promise(resolve => setTimeout(resolve, 80));
    expect(onAnalyzedSample).not.toHaveBeenCalledWith(expect.objectContaining({ frame_index: 12 }));
    expect(onAnalyzedSample).not.toHaveBeenCalledWith(expect.objectContaining({ frame_index: 13 }));
    expect(container.querySelector('[data-track-id]')).not.toBeInTheDocument();
  });

  it('keeps a zero-object detector frame as explicit current-run truth', async () => {
    const onAnalyzedSample = vi.fn();
    const { container } = renderFeed({ onAnalyzedSample });
    wireVideo(container.querySelector('video'));
    act(() => window.dispatchEvent(new CustomEvent('netraksh-tracking-frame', {
      detail: sample({ frame_index: 14, video_time: 0.5, tracks: [], person_count: 0, track_count: 0 }),
    })));
    await waitFor(() => expect(onAnalyzedSample).toHaveBeenLastCalledWith(expect.objectContaining({
      frame_index: 14, person_count: 0, vehicle_count: 0, track_count: 0,
    })));
  });

  it('offers raw SOURCE PREVIEW as an explicit optional mode without analysis control calls', async () => {
    const onStartAnalysis = vi.fn();
    const onPauseAnalysis = vi.fn();
    const { container } = renderFeed({ onStartAnalysis, onPauseAnalysis });
    const video = wireVideo(container.querySelector('video'));
    act(() => window.dispatchEvent(new CustomEvent('netraksh-tracking-frame', { detail: sample() })));
    await waitFor(() => expect(screen.getByTitle('View source preview')).toBeEnabled());
    fireEvent.click(screen.getByTitle('View source preview'));
    expect(screen.getByRole('button', { name: /VIEW ANALYZED/ })).toHaveAttribute('data-playback-mode', 'source-preview');
    expect(video).toHaveAttribute('controls');
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
    expect(onStartAnalysis).not.toHaveBeenCalled();
    expect(onPauseAnalysis).not.toHaveBeenCalled();
    act(() => window.dispatchEvent(new CustomEvent('netraksh-tracking-frame', {
      detail: sample({ sequence: 2, frame_index: 13, video_time: 0.45 }),
    })));
    expect(screen.getByRole('button', { name: /VIEW ANALYZED/ })).toHaveAttribute('data-playback-mode', 'source-preview');
  });

  it('replays an accepted completed timeline in source order without triggering analysis', async () => {
    const onAnalyzedSample = vi.fn();
    const onStartAnalysis = vi.fn();
    const timeline = [
      sample({ frame_index: 20, video_time: 0 }),
      sample({ sequence: 2, frame_index: 24, video_time: 0.15 }),
    ];
    const { container } = renderFeed({
      sourceRunState: 'COMPLETED',
      telemetryStatus: 'COMPLETED',
      completedTimeline: timeline,
      completedSummary: { ...scope, final_video_time: 0.15 },
      onAnalyzedSample,
      onStartAnalysis,
    });
    const replayVideo = wireVideo(container.querySelector('video'));
    fireEvent.seeked(replayVideo);
    await waitFor(() => expect(onAnalyzedSample).toHaveBeenLastCalledWith(expect.objectContaining({ frame_index: 24 })), { timeout: 1500 });
    const committed = onAnalyzedSample.mock.calls.map(call => call[0]?.frame_index).filter(Boolean);
    expect(committed).toEqual(expect.arrayContaining([20, 24]));
    expect(committed.indexOf(20)).toBeLessThan(committed.indexOf(24));
    expect(onStartAnalysis).not.toHaveBeenCalled();
  });

  it('enters analyzed replay near the current source time instead of the final frame', async () => {
    const onAnalyzedSample = vi.fn();
    const timeline = [0, 1, 2, 3, 4, 5, 6, 7, 8].map((time, index) => sample({
      sequence: index + 1, frame_index: index * 30, video_time: time,
    }));
    const { container } = renderFeed({
      sourceRunState: 'COMPLETED', telemetryStatus: 'COMPLETED',
      completedTimeline: timeline,
      completedSummary: { ...scope, final_video_time: 8 }, onAnalyzedSample,
    });
    const video = wireVideo(container.querySelector('video'));
    await waitFor(() => expect(screen.getByTitle('View source preview')).toBeEnabled());
    fireEvent.click(screen.getByTitle('View source preview'));
    video.currentTime = 4.8;
    fireEvent.click(screen.getByTitle('View analyzed frames'));
    await waitFor(() => expect(onAnalyzedSample).toHaveBeenLastCalledWith(expect.objectContaining({
      frame_index: 150, video_time: 5,
    })));
    expect(video.currentTime).toBe(5);
    expect(screen.getByRole('button', { name: 'Pause analyzed replay' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Pause analyzed replay' }));
    expect(screen.getByRole('button', { name: 'Play analyzed replay' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next analyzed frame' }));
    await waitFor(() => expect(onAnalyzedSample).toHaveBeenLastCalledWith(expect.objectContaining({
      frame_index: 180, video_time: 6,
    })));
    fireEvent.click(screen.getByTitle('View source preview'));
    expect(video.currentTime).toBe(6);
  });

  it('does not call a restored durable source NO VIDEO SOURCE while transport is absent', () => {
    render(<VideoFeed
      cameraId="cam-border-01"
      sourceMode="durable"
      expectedSessionId="stored-source"
      sourceRestoring
      telemetryStatus="WAITING"
    />);
    expect(screen.queryByText('NO VIDEO SOURCE')).not.toBeInTheDocument();
    expect(screen.getByText(/RESTORING STORED SOURCE/)).toBeInTheDocument();
  });
});
