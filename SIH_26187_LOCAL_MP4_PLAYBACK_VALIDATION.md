# SIH 26187 — Local MP4 Playback Remediation

Date: 2026-09-24

## Original failure reproduced

Uploading `demo/videos/vtest.mp4` displayed the uploaded filename, but the browser showed `Failed to load video media.` and no native `<video>` element remained after telemetry arrived. The browser console also showed `POST /api/dashboard/video/analyze` returning `404 Video preview file not found`.

## Root cause

The upload endpoint correctly returned a direct MP4 preview with `preview_url` while ffmpeg was unavailable (`ffmpeg_available: false`). The frontend nevertheless sent a synthetic `preview_name` (`uploaded_<session>_preview.mp4`) to `/video/analyze`; that converted file did not exist, so analyze returned 404. The upload error handler then revoked the local object URL and cleared the media source. Separately, `VideoFeed` preferred the analyzed JPEG over the native media element, making native playback impossible to verify once telemetry was available.

## Remediation

- Only send `preview_name` when the server reports an actual ffmpeg conversion (`ffmpeg_available: true`).
- Keep a browser-compatible `mediaUrl` as the primary rendered element in `VideoFeed`; use the analyzed JPEG only when there is no browser media URL.
- Preserve the browser-uploaded source/session handoff in the demo edge worker.

## Live validation

- Camera 1 upload: PASS — `uploaded_b9788f50-dc88-48a2-9e2d-9636c6b0ca87.mp4`.
- Native element: PASS — `readyState=4`, `duration=79.5s`, `960×720`, no `HTMLMediaElement.error`.
- Play: PASS — native video advanced from `0.0s` to `0.88s`.
- Pause: PASS — native video paused at `5.75s`.
- Seek: PASS — ArrowRight seek moved playback to `15.0s` while remaining decoded.
- Start/Analyze: PASS — Camera 1 ONLINE, telemetry LIVE, session `b9788f50`, analyzed frame `1948`, 6 persons / 2 vehicles / 8 tracks.
- Stop/restart: PASS — source metadata persisted and Camera 1 returned ONLINE after restart.
- Hard refresh: PASS — authenticated preview reloaded and native MP4 decoded again.
- Final browser state: Camera 1 selected with the MP4 preview visible and telemetry live.

## Media endpoint evidence

- URL: `/api/dashboard/video/current/media`
- Auth: Bearer token required and supplied by `authFetch`.
- Response: `200 OK`
- Content-Type: `video/mp4`
- Content-Length: `53193629`
- Accept-Ranges: `bytes` header present.
- Browser path: authenticated fetch → Blob object URL → native `<video>`.
- Direct Range probe returned `200` with the full body rather than `206`; this does not block the current authenticated Blob playback path and remains a separate server streaming improvement.

## Unsupported AVI

AVI without ffmpeg remains intentionally honest: it is saved for edge analysis, no browser preview is claimed, and the UI reports that Chromium playback requires an MP4 preview. An analyzed-frame fallback is not counted as MP4 playback success.

