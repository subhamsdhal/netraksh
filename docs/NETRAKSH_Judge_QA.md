# NETRAKSH: Judge Q&A Bank

## PROBLEM & ARCHITECTURE
1. **JUDGE QUESTION**: Why use Edge computing instead of streaming all video to the cloud?
   * **BEST ANSWER**: Bandwidth constraints at remote borders make streaming full HD video impossible. By processing frames at the edge and only sending lightweight telemetry and metadata, we massively reduce bandwidth requirements.
   * **EVIDENCE**: Our architecture runs YOLO locally and syncs JSON metadata payloads.
   * **LIMITATION**: The edge node requires local compute hardware (e.g., Jetson).

2. **JUDGE QUESTION**: What happens when the Edge node loses internet connection?
   * **BEST ANSWER**: It enters offline mode. It stores all detections and telemetry locally in an SQLite database. When connection is restored, our store-and-forward sync client pushes the queued data to the backend automatically.
   * **EVIDENCE**: `SyncClient` and `CameraHealth` modules in `edge/sync`.
   * **LIMITATION**: Local storage capacity limits how long the edge can stay offline.

3. **JUDGE QUESTION**: How do you handle database locks on the edge during high traffic?
   * **BEST ANSWER**: SQLite provides local buffering, and we use WAL mode with retry pragmas, but heavy local contention remains a known reliability limitation during high-throughput evidence packaging.
   * **EVIDENCE**: `edge/sync/` configurations.
   * **LIMITATION**: Relational SQLite isn't meant for massive concurrent writes.

## AI & COMPUTER VISION
4. **JUDGE QUESTION**: Where is your accuracy metric for YOLO (mAP)?
   * **BEST ANSWER**: We have not run a formal mAP benchmark against a custom dataset because this is an MVP. We are using a pre-trained YOLO model to demonstrate the pipeline architecture.
   * **EVIDENCE**: The code uses standard generic YOLOv8 weights for the prototype.
   * **LIMITATION**: Real deployment would require fine-tuning on a specialized border dataset.

5. **JUDGE QUESTION**: How did you evaluate tracking?
   * **BEST ANSWER**: Tracking uses standard algorithms (ByteTrack/BoT-SORT concepts) provided by the community/OpenCV. We evaluated it empirically on local sample videos to prove the pipeline flow.
   * **EVIDENCE**: Tracker implementations in the edge pipeline.
   * **LIMITATION**: No formal MOTA (Multi-Object Tracking Accuracy) scores computed yet.

6. **JUDGE QUESTION**: Is behavioral intelligence actually deep learning?
   * **BEST ANSWER**: No. Currently, it is a rule-based system running on top of AI tracking data. It calculates geometric intersections (e.g., line crossing) from AI bounding boxes rather than using a complex spatio-temporal neural network for anomaly detection.
   * **EVIDENCE**: `edge/rules/` contains geometric rule definitions.
   * **LIMITATION**: It is not "deep learning behavioral analysis" itself.

7. **JUDGE QUESTION**: How do you prove cross-camera identity?
   * **BEST ANSWER**: In this prototype, we use classical spatio-temporal cross-camera correlation (matching timestamps, camera topology, and object classes) rather than deep-learning biometric ReID.
   * **EVIDENCE**: `backend/services/cross_camera.py`.
   * **LIMITATION**: It does not guarantee biometric identity matching across cameras.

8. **JUDGE QUESTION**: How did you evaluate ANPR and Face Recognition?
   * **BEST ANSWER**: We integrated lightweight prototype implementations (e.g. LBPH/SFace concepts) to prove the data flow. They are not production-ready for highly unconstrained environments.
   * **EVIDENCE**: Source files in `edge/detection/`.
   * **LIMITATION**: Accuracy (CER/FAR/FRR) has not been quantified on diverse datasets.

## SECURITY & CRYPTO
9. **JUDGE QUESTION**: Is your blockchain real?
   * **BEST ANSWER**: No. We implemented a `MockBlockchainAdapter` to prototype how our system would submit alert hashes to a permissioned ledger like Hyperledger Fabric.
   * **EVIDENCE**: `backend/services/blockchain.py` explicitly states MOCK.
   * **LIMITATION**: The real ledger infrastructure is not deployed.

10. **JUDGE QUESTION**: Can evidence tampering be detected?
    * **BEST ANSWER**: Yes. The edge signs every event payload using Ed25519 keys and chains the hashes. If an operator alters the database, the backend verification will fail because the signature and hash chain won't match.
    * **EVIDENCE**: `edge/evidence/packager.py` and `backend/api/events.py` verification logic.
    * **LIMITATION**: Requires secure provisioning of private keys to the edge.

11. **JUDGE QUESTION**: Can audit-log tampering be detected?
    * **BEST ANSWER**: The application-level audit log is currently mutable (stored in standard SQL). The cryptographically immutable chain applies to *detection events* from the edge, not the backend administrative audit logs.
    * **EVIDENCE**: `backend/security/auth.py` standard insert for audit logs.
    * **LIMITATION**: Audit logs lack their own cryptographic chaining.

12. **JUDGE QUESTION**: Can two operators see each other's data?
    * **BEST ANSWER**: No. Our backend enforces Command-Level Resource Isolation. An operator assigned to "Command A" cannot query, export, or receive WebSocket broadcasts for cameras in "Command B".
    * **EVIDENCE**: `auth.get_command_filter` restricts SQL queries natively.
    * **LIMITATION**: Admin and Auditor roles have global access by design.

13. **JUDGE QUESTION**: Can a disabled user keep a WebSocket?
    * **BEST ANSWER**: JWT authentication and command-scoped WebSocket delivery are enforced. However, a user disabled *after* connection may remain connected until token expiry or natural disconnection.
    * **EVIDENCE**: Connection relies on JWT validation at handshake.
    * **LIMITATION**: Real-time session revocation via Redis/DB checks per-frame is omitted for performance.

## RELIABILITY & SCALABILITY
14. **JUDGE QUESTION**: How do you prevent duplicate alert acknowledgement?
    * **BEST ANSWER**: Alert acknowledgement uses an atomic state transition in the database so only one concurrent request can transition the alert from ALERTED to ACKNOWLEDGED; competing requests receive a safe conflict response.
    * **EVIDENCE**: `backend/api/alerts.py` implements `UPDATE ... WHERE lifecycle_state = 'ALERTED'`.
    * **LIMITATION**: Relies on relational DB locks.

15. **JUDGE QUESTION**: What happens if the private key is lost on the edge?
    * **BEST ANSWER**: The node will fail to sign new evidence packages. It would require re-provisioning a new keypair and registering the new public key on the backend.
    * **EVIDENCE**: Ed25519 implementation.
    * **LIMITATION**: Automated key rotation protocol is not fully implemented.

*(Note: These responses represent the core defensive strategy. The system is presented as a technically sound, verifiable MVP prototype rather than a flawless national production system.)*
