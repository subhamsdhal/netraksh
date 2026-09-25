# NETRAKSH: Final Demo Runbook

## PRE-DEMO CHECKLIST

Before beginning the presentation, the presenter must verify the following state:

1. **Backend starts**: Run `python backend/main.py`. Verify `Uvicorn running on port 8000`.
2. **Database reachable**: Check Supabase connection logs in the backend terminal.
3. **Edge starts**: Run `python edge/main.py`. Verify pipeline initialization and OpenCV frame grabber active.
4. **Camera/video available**: Ensure `demo/sample_videos/border_feed.mp4` or the configured RTSP stream is accessible.
5. **WebSocket available**: Check browser DevTools (F12) -> Network -> WS to ensure `101 Switching Protocols`.
6. **Frontend available**: Run `npm run dev` in `frontend/`. Access `http://localhost:5173`.
7. **Login credentials verified**: Ensure the OPERATOR test user is active (`operator1` / `testpass123`).
8. **Command scope verified**: Verify the operator dashboard only shows Command Area 'East'.
9. **Alert test path verified**: Ensure geometric rule rules trigger on the edge and populate the UI.
10. **Evidence verification tested**: Manually download an evidence payload JSON and click "Verify" in the UI. Ensure green checkmark (valid signature).

## LIVE DEMO ORDER (5 Minutes)

1. **Login**: Screen shows standard auth. Presenter emphasizes RBAC.
2. **Dashboard**: Highlight localized telemetry and command isolation.
3. **Live Video**: Navigate to camera view. Show YOLOv8 bounding boxes and ByteTrack IDs.
4. **Detection**: Point out specific detected classes (e.g., Person, Vehicle).
5. **Tracking & Behavior**: Point out a tracked entity crossing a defined boundary zone.
6. **Alert generation**: The UI pop-up (WebSocket pushed) appears.
7. **ACK**: Click Acknowledge. Explain the atomic database transition protecting against race conditions.
8. **Evidence**: Open the evidence modal for the alert.
9. **Crypto Verify**: Highlight the SHA-256 hash and Ed25519 signature. Click verify to prove zero tampering.
10. **Map**: Show the geospatial correlation.
11. **Analytics**: Show the localized charts.
12. **Security / Isolation**: Emphasize that all shown data is tightly scoped.
13. **Closing**: Transition back to PPT for Final Limitations and Scope.

## FAILURE RECOVERY

If something goes wrong during the live demo:

- **Camera fails/black screen**: Immediately switch to the pre-recorded fallback video feed tab. State: "This mimics a hardware failure at the pole; let's look at the buffered evidence from before the drop."
- **Backend is slow**: Do not refresh furiously. Wait 5 seconds. Explain that edge buffering is protecting the pipeline.
- **WebSocket reconnects**: A red indicator will appear. Explain: "The UI has detected a network blip and is automatically applying exponential backoff to reconnect, just as a remote outpost would."
- **Alert does not appear**: Open the Events Log. State: "The detection occurred but did not meet the severity threshold for an interruptive alert."
- **Network disconnects**: Physically disconnect laptop Wi-Fi. Show the Edge terminal queuing SQLite events. Reconnect Wi-Fi and show the events flushing to the backend.
