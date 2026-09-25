# Phase 4 WP-4.2: Network Trust Boundary

## Trusted Proxy Architecture (mTLS)

To protect the Central Backend from direct public exposure while still allowing edge nodes to communicate across untrusted networks (e.g. the internet), NETRAKSH utilizes a Trusted Proxy topology.

### Ingress Flow
1. **Edge Node** -> Initiates TLS connection (validating server CA).
2. **Edge Node** -> Provides its Client Certificate (`camera-*.crt`).
3. **TLS Proxy (e.g. Nginx, Envoy)** -> Terminates mTLS. Validates Client Certificate against known CA.
4. **TLS Proxy** -> Computes SHA-256 fingerprint of the verified client certificate.
5. **TLS Proxy** -> Forwards request to Central Backend via private network, injecting the `X-Client-Fingerprint` header.
6. **Central Backend** -> Consumes the header via `mTLS_Identity` dependency and maps it to a `CameraKey`.

### Network Restrictions (Firewall)
- The **TLS Proxy** is the ONLY component exposed to the public internet on port 443.
- The **Central Backend** (FastAPI) is deployed in a private subnet. It MUST NOT be directly accessible from the internet to prevent malicious actors from spoofing the `X-Client-Fingerprint` header.
- **PostgreSQL** and **MinIO** are similarly deployed in private subnets and accessed exclusively by the Central Backend. Edge nodes have no routing or credentials to directly reach these datastores.

### Edge Network Outbound
- Edge nodes require **outbound-only** network rules on TCP port 443 to the TLS Proxy.
- No inbound internet ports are required to be open on the physical Edge device, significantly reducing its attack surface in field deployments.
