# NETRAKSH: Final Technical Report
**AI-Based Intelligent Video Analytics Platform for Border Surveillance**
**SIH Problem Statement: 26187**

## EXECUTIVE SUMMARY
NETRAKSH is an advanced MVP/prototype platform designed to transform existing, passive CCTV infrastructure along remote borders into an active, intelligent threat-detection ecosystem. By deploying an Edge-to-Cloud architecture, the system operates resiliently under intermittent network conditions, securing AI-generated threat detections via cryptographically verifiable evidence chains.

## PROBLEM STATEMENT
Border Security Forces operate extensive CCTV networks. Monitoring these manually is prone to human fatigue. Furthermore, border regions face severe network constraints, making continuous cloud streaming of high-definition video unfeasible and costly. 

## EXISTING SYSTEM LIMITATIONS
- High bandwidth dependence.
- Single points of failure during network outages.
- Lack of cryptographic integrity for video evidence.
- Siloed command structures lacking real-time, isolated threat routing.

## PROPOSED SYSTEM
NETRAKSH processes video locally at the Edge, reducing bandwidth dependence. Only intelligent event metadata and evidentiary snapshots are synced to the Command Center. The system ensures operational continuity via a store-and-forward architecture and guarantees data integrity via cryptographic signing.

## OBJECTIVES
- Reduce dependence on continuous full-video cloud transmission.
- Maintain operational logging during network outages.
- Prevent post-incident tampering of alerts.
- Ensure strict Role-Based Access Control (RBAC) and Command Isolation.

## SYSTEM ARCHITECTURE
A hybrid Edge-Cloud architecture comprising:
1. **Edge Node**: Ingests RTSP streams, runs AI models, signs evidence, and queues data.
2. **Backend Services**: Handles RBAC, Alert routing, WebSocket broadcasting, and Blockchain mockup.
3. **Command Center**: A React-based UI scoped tightly to operator permissions.

## EDGE ARCHITECTURE
- **Ingestion**: Standard RTSP stream decoding.
- **Processing**: Localized AI pipelines.
- **Evidence Packager**: Hashes and signs payloads using Ed25519.
- **Sync Client**: Buffers data in local SQLite and syncs via HTTPS to the cloud.

## BACKEND ARCHITECTURE
Built on FastAPI and PostgreSQL (via Supabase), the backend serves as the centralized orchestrator. It verifies incoming cryptographic signatures, triggers alerts, and manages secure WebSocket distribution to authorized operators.

## FRONTEND / COMMAND CENTER
A React+Vite SPA providing real-time situational awareness, alert lifecycle management, and evidence verification.

## AI / COMPUTER VISION PIPELINE
*Integrated prototype pipelines are present for demonstrating the end-to-end architecture, but formal accuracy evaluation on representative datasets has not yet been completed.*

### YOLO DETECTION
Prototype utilizes generic YOLOv8 weights for person/vehicle localization. (mAP: NOT EVALUATED)

### OBJECT TRACKING
Leverages established tracking concepts (e.g. ByteTrack) to maintain object identity across frames. (MOTA / IDF1: NOT EVALUATED)

### BEHAVIORAL RULE ENGINE
Rule-based behavioral intelligence operating on tracked detections (e.g., line-crossing geometry). Not based on deep-learning anomaly detection.

### ANPR
Prototype pipeline present for license plate localization. (CER: NOT EVALUATED)

### FACE RECOGNITION
Prototype pipeline present using local encodings. (FAR/FRR: NOT EVALUATED)

### CROSS-CAMERA CORRELATION
Spatio-temporal cross-camera correlation using camera context, timing, object class and movement constraints (not equivalent to biometric identity-level ReID).

## ALERT SYSTEM
Converts rule violations into actionable Alerts. Alert acknowledgement uses an atomic state transition so only one concurrent request can transition the alert from ALERTED to ACKNOWLEDGED; competing requests receive a safe conflict response.

## OFFLINE STORE-AND-FORWARD
NETRAKSH supports store-and-forward operation: edge data can be buffered locally during connectivity loss and synchronized when connectivity returns, subject to queue/storage and ordering limitations.

## CRYPTOGRAPHIC EVIDENCE
Detections are bundled with base64 images and JSON metadata, hashed via SHA-256, signed via Ed25519 at the Edge, and linked in a cryptographic chain.

## AUDIT TRAIL
Cryptographically verifiable detection evidence chain, alongside standard (mutable) application audit logging for administrative actions.

## RBAC & COMMAND ISOLATION
Strict Role-Based Access Control enforcing boundary isolation. Operators only receive data and API access mapped to their specific Command ID.

## WEBSOCKET SECURITY
JWT authentication and command-scoped WebSocket delivery are enforced. A user disabled after connection may remain connected until token expiry or disconnection.

## SECURITY MODEL
Defends against IDOR, race conditions, and evidence tampering.

## RELIABILITY MODEL
Withstands network outages via Edge SQLite buffering and handles concurrent Alert modification via relational database atomicity.

## TESTING & RESULTS
- **Crypto Verification**: Verified via unit tests ensuring tampered payloads are rejected.
- **Command Isolation**: Verified via simulated IDOR tests.
- **Concurrent ACK/CLOSE**: Verified. 5 concurrent requests yield 1 success, 4 HTTP 409 Conflicts.
- **WebSocket Auth/Scope**: Verified server-side filtering drops out-of-scope clients.

## DEPLOYMENT
- Frontend: Vercel
- Backend: Render
- DB: Supabase (PostgreSQL)

## KNOWN LIMITATIONS
See `KNOWN_LIMITATIONS.md` for a complete breakdown of prototype constraints, including AI accuracy evaluation absence and Mock ledger usage.

## FUTURE ENHANCEMENTS
- Fine-tuning YOLOv8 on specific border terrain datasets.
- Integration with true HSMs for Edge key storage.
- Deployment to a real Hyperledger Fabric network.

## CONCLUSION
NETRAKSH successfully demonstrates a scalable, secure, and offline-resilient architecture for AI-driven border surveillance, providing a highly defensible MVP for the SIH challenge.
