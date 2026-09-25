# NETRAKSH: Final PPT Content Structure

## SLIDE 1
**NETRAKSH**
*AI-Based Intelligent Video Analytics Platform for Border Surveillance*
*(Subtitle: SIH Problem Statement 26187)*

## SLIDE 2
**Problem Statement**
* Remote border outposts monitor hundreds of CCTV feeds manually.
* High risk of human fatigue causing missed intrusions.
* Extreme bandwidth limitations prevent continuous cloud streaming of raw HD video.
* Lack of verifiable evidence if a local system is compromised.

## SLIDE 3
**Why Existing Infrastructure Is Insufficient**
* **Dumb Cameras**: Standard CCTVs only record; they do not detect.
* **Network Fragility**: Cloud-only AI fails when remote networks drop.
* **Siloed Operations**: Alerts cannot easily cross command boundaries securely.
* **Tamper Risk**: Video files can be deleted or altered post-incident.

## SLIDE 4
**NETRAKSH Solution**
* **Edge Intelligence**: AI models run directly on the Edge node, processing local RTSP streams.
* **Bandwidth Optimization**: We sync lightweight event metadata instead of heavy video streams.
* **Offline Resilience**: A store-and-forward queue handles network drops gracefully.
* **Cryptographic Evidence**: Every detection is signed and chained on the Edge.

## SLIDE 5
**System Architecture**
*(Diagram: Edge Node -> Secure Sync -> Backend -> Command Center)*
* **Edge Node**: Ingests RTSP, runs YOLO/Tracking, signs evidence, buffers in SQLite.
* **Backend**: FastAPI + PostgreSQL. Verifies signatures, enforces RBAC, routes Websockets.
* **Command Center**: React UI providing isolated situational awareness.

## SLIDE 6
**AI / Video Intelligence Pipeline**
*(Flowchart: Video -> Detection -> Tracking -> Rules -> Alert -> Evidence)*
* **Detection**: YOLOv8 prototype for localization.
* **Tracking**: ByteTrack principles for identity continuity.
* **Rules**: Geometric behavior evaluation (e.g., Line Crossing).
* **Alert**: Automated escalation.

## SLIDE 7
**Offline / Store-and-Forward Architecture**
*(Diagram showing Edge dropping network, buffering to SQLite, and syncing upon reconnect)*
* Edge data can be buffered locally during connectivity loss.
* Synchronized when connectivity returns.
* Preserves critical threat intelligence in austere environments.

## SLIDE 8
**Cryptographically Verifiable Evidence**
* **SHA-256**: Hashes the image and metadata payload.
* **Ed25519**: Signs the hash using the Edge's private key.
* **Hash Chain**: Links the current event to the previous event, making historical deletion impossible without detection.

## SLIDE 9
**Security & Command Isolation**
* **RBAC**: Operator vs. Admin roles.
* **Command-Level Isolation**: Operators only see alerts and cameras mapped to their specific Command ID.
* **WebSocket Scoping**: Broadcasts are filtered server-side to prevent data leakage.

## SLIDE 10
**Alert Intelligence / Operational Workflow**
* **Atomic Transitions**: Acknowledging an alert uses atomic SQL updates to guarantee exact accountability and prevent race conditions.
* Safe conflict responses ensure multiple operators don't corrupt alert states.

## SLIDE 11
**Command Center / UI**
*(Insert 2-3 High-Quality Verified Screenshots)*
* Dashboard View
* Live Camera View
* Verifiable Evidence View

## SLIDE 12
**Testing & Results**
* **Security Verified**: Simulated IDOR (Insecure Direct Object Reference) testing passed.
* **Concurrency Verified**: Atomic ACK logic tested with 5 concurrent requests (1 success, 4 safe conflicts).
* **Crypto Verified**: Tampered payloads correctly rejected by the backend verifier.

## SLIDE 13
**Innovation + Advantages**
* Transforming AI threat detections into verifiable, tamper-evident cryptographic artifacts.
* Unifying edge computing with zero-trust backend isolation.
* Designed ground-up for network-austere environments.

## SLIDE 14
**Limitations + Future Scope + Closing**
* **Limitations**: Mock Ledger Adapter, generic YOLO weights, and SQLite local contention limits.
* **Future Scope**: Fine-tuning AI on border-specific datasets, hardware security module (HSM) integration, and deployment to a real Hyperledger network.
* **Closing**: NETRAKSH proves that we can unify AI analytics, offline resilience, and cryptographic evidence into a single, secure platform.
