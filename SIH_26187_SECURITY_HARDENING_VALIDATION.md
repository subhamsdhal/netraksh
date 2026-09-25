# Executive Summary

Security hardening preserved the validated ANPR, face, night, evidence, and
dashboard work. Webhook destination policy/signing, bounded video uploads, and
login throttling were added and locally regression-tested.

# Threat Scope

Local controlled fixtures only; no external hosts, metadata services, CCTV, or
real-account brute force was used.

# Webhook Security

**BEFORE** direct URL POSTs accepted SSRF-prone destinations, followed redirects,
and had no signature. **FIX** HTTP(S)-only DNS/IP policy rejects loopback,
private, link-local, unspecified, and multicast addresses unless
`WEBHOOK_ALLOWED_HOSTS` explicitly allowlists a host; redirects are disabled;
event ID, timestamp, and optional HMAC headers are emitted. **TEST** local URL
policy and HMAC fixtures. **CURRENT STATUS** FIXED AND VERIFIED for policy and
signing; durable retry worker remains partial.

# Edge Identity

**BEFORE** bearer-only deployments lacked a camera authorization map.
**FIX** existing mTLS registry, status checks, and event edge/camera binding are
preserved. **TEST** mTLS/impersonation fixtures. **CURRENT STATUS** MITIGATED;
per-device bearer provisioning remains an operational requirement.

# Authentication

**BEFORE** login lacked endpoint throttling. **FIX** `/auth/token` is limited to
5/minute per source IP; JWT expiry and inactive-user checks remain enforced.
**TEST** auth regression. **CURRENT STATUS** FIXED AND VERIFIED.

# WebSocket Security

**BEFORE** query-string token leakage was a historical risk. **FIX** subprotocol
authentication remains in use. **TEST** reconnect/auth regression and browser
check. **CURRENT STATUS** FIXED AND VERIFIED.

# RBAC

**BEFORE** role boundaries required regression. **FIX** no weakening introduced.
**TEST** ADMIN/OPERATOR/AUDITOR/unauthenticated matrix across camera,
watchlist, event, alert, audit, integration, ANPR, face, and diagnostics APIs.
**CURRENT STATUS** FIXED AND VERIFIED.

# Upload Security

**BEFORE** uploads were copied without an explicit bounded stream/signature.
**FIX** 1 MiB streaming, 200 MiB cap, zero-byte rejection, server filenames,
and MP4/MOV/AVI/WebM/MKV signature checks. **TEST** oversized, empty, fake,
unsupported, and traversal fixtures. **CURRENT STATUS** FIXED AND VERIFIED.

# Biometric Input Protection

**BEFORE** protections existed from the prior phase. **FIX** valid base64,
2 MiB, quality, and exactly-one-face checks remain enforced. **TEST** 42 focused
face tests. **CURRENT STATUS** FIXED AND VERIFIED.

# Media Protection

**BEFORE** public static media was a prior finding. **FIX** authenticated media
routes only. **TEST** unauthenticated denied, authorized allowed, static bypass
absent. **CURRENT STATUS** FIXED AND VERIFIED.

# Path Traversal

**BEFORE** media references needed confinement. **FIX** resolved-path confinement
rejects relative, encoded, absolute, Windows, and mixed-separator traversal.
**TEST** existing traversal assertions. **CURRENT STATUS** FIXED AND VERIFIED.

# Secrets

**BEFORE** local development keys exist. **FIX** production placeholder checks,
ignored private keys, no frontend exposure, and redacted scan. **TEST** safe
pattern scan without values. **CURRENT STATUS** MITIGATED.

# CORS

**BEFORE** production validation was required. **FIX** wildcard origins rejected
and explicit origins used. **TEST** settings/live header checks. **CURRENT STATUS**
FIXED AND VERIFIED.

# Evidence Integrity

**BEFORE** ANPR/face/night metadata required rechecking. **FIX** existing
versioned signed/encrypted contract preserved. **TEST** signature/hash/tamper
tests. **CURRENT STATUS** FIXED AND VERIFIED for the current contract.

# Retention

**BEFORE** comprehensive configurable retention was absent. **FIX** unsynced
evidence is preserved and cleanup limits are documented as follow-up.
**TEST** no destructive cleanup run. **CURRENT STATUS** PARTIAL.

# Edge Disk Safety

**BEFORE** hard disk/outbox caps were incomplete. **FIX** queue health remains
observable and unsynced evidence is not silently discarded. **TEST** offline
queue regression. **CURRENT STATUS** PARTIAL.

# Offline Recovery

**BEFORE** restoration needed revalidation. **FIX** stable event IDs and SQLite
outbox retry path retained. **TEST** controlled offline/restore sync regression.
**CURRENT STATUS** FIXED AND VERIFIED.

# Night Event Closure

**BEFORE** full dark fixture browser closure was missing. **FIX** synthetic
very-low-light motion reaches signed evidence and edge outbox. **TEST** real
EdgePipeline emitted `MOTION_FALLBACK`; backend/browser closure was not repeated.
**CURRENT STATUS** PARTIAL; not an accuracy claim.

# Tests

Focused security run: 28 passed; 2 Windows pytest temp-cleanup setup errors
unrelated to assertions. Prior broader regression: 157 passed. Face suite: 42
passed. Frontend: 13 passed and build passed. Dependency CVE status: UNKNOWN.

# Remaining Risks

1. Webhook delivery is still best-effort rather than a durable retry-state
   database outbox.
2. Edge, metrics, demo-video, and biometric retention limits need deployment
   policy and cleanup workers.
3. Full night event DB → WebSocket → browser closure remains partial.
4. PostgreSQL/container validation and dependency CVE database scanning were
   unavailable.
