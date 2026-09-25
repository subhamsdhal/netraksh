# NETRAKSH: Known Limitations

NETRAKSH is currently an advanced MVP/prototype designed to demonstrate an end-to-end secure, offline-resilient AI pipeline. As such, it contains the following known limitations which must be addressed prior to any national production deployment:

## 1. AI Accuracy Evaluation
Formal AI accuracy evaluation (mAP, MOTA) on a representative dataset has not been completed. The system utilizes generic weights.

## 2. Model Fine-Tuning
A specialized border dataset/fine-tuning is absent. The current YOLOv8 model has not been trained on specific border terrain or camouflage datasets.

## 3. Behavioral Intelligence
The system uses rule-based behavior (e.g., geometric line-crossing intersections) rather than deep-learning anomaly detection.

## 4. Cross-Camera Correlation
Cross-camera correlation relies on spatio-temporal boundaries (time, location, object class) and is not equivalent to biometric identity-level ReID.

## 5. Blockchain Integration
The repository uses a `MockBlockchainAdapter` to simulate integration with a permissioned ledger. It is not currently deployed to a live Hyperledger Fabric network.

## 6. Audit Logging
While edge detection evidence is cryptographically signed and chained, the standard administrative application AuditLog is mutable by database administrators.

## 7. Edge Storage Contention
SQLite provides local buffering for offline operation, but heavy local DB contention remains a known reliability limitation during high-throughput evidence packaging.

## 8. Store-and-Forward Constraints
The offline queue is subject to storage limitations on the edge device and lacks guaranteed at-least-once reconciliation logic if the local SQLite file is corrupted.

## 9. Storage Retention
Video evidence storage and retention policies are currently constrained by cloud provider database/object storage limits in the prototype environment.

## 10. WebSocket Revocation
JWT authentication and command-scoped WebSocket delivery are enforced. However, a user disabled *after* connection may remain connected until token expiry or natural disconnection.

## 11. Key Management
Edge private keys are stored locally. Integration with Hardware Security Modules (HSM) or secure enclaves is required for production key provisioning.

## 12. Disaster Recovery
Formal RPO (Recovery Point Objective) and RTO (Recovery Time Objective) limitations for the Supabase backend have not been quantified beyond standard provider backups.

## 13. Camera Scalability
The number of concurrent RTSP streams an edge node can process is strictly hardware-dependent and has not been stress-tested for maximum capacity on specific edge hardware (e.g., Jetson Orin).
