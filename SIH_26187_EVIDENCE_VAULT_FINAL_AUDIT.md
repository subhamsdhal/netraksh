# NETRAKSH / SIH 26187 — Cryptographic Evidence Vault Final Audit

Audit date: 2026-09-25 (Asia/Calcutta)  
Route: `http://127.0.0.1:5173/evidence`  
Database: `data/demo/sih_demo.db`

# Scope

This audit was restricted to the Cryptographic Evidence Vault, its evidence-specific API contract, shared response fields required by that contract, and evidence-focused tests. No historical evidence, signed payload, hash, signature, predecessor link, or bulk integrity status was rewritten. No unrelated NETRAKSH module was modified for this work.

# UI Components

- Evidence list with authoritative total, deterministic 50-record pages, and explicit hash, signature, and chain labels.
- Search and Camera, Decision, Event Type, Stream, and Integrity filters.
- Evidence detail with event/evidence timestamps, camera, stream/session, event type, detection metadata, storage metadata, schema/crypto versions, signing key ID, reliability data, and protected media.
- Five independent integrity steps: Event Data, SHA-256 Content Hash, Ed25519 Signature, Local Chain, and External Anchor.
- Loading, populated, empty-filter, error/retry, missing-media, access-denied, missing-key, synchronization-timeout, and no-selection states.
- Previous/Next pagination and authenticated full-result CSV export.

Before remediation, the route showed only the newest 100 generic event records, applied search/filters only to that client-side subset, had no total/pagination/error/retry state, labeled rows `SIGNED` from signature presence, and represented local-chain/mock-anchor state ambiguously. The initial route was documented before edits and the initial capture is `artifacts/evidence_vault_final_audit_20260925/evidence_list.png`.

# Controls Tested

Eleven visible control classes were exercised: CSV export, search, camera filter, decision filter, event-type filter, stream filter, integrity filter, evidence-row selection, Previous, Next, and Verify Integrity Chain. All are working. There are no unexplained dead controls. Copy, sort, date filter, and a separate refresh button are not present.

# API Endpoints

| UI function | Endpoint | Expected | Observed |
|---|---|---|---|
| Paginated vault | `GET /events/evidence-vault` | Authenticated stable page and total | 200; 50 items; stable `timestamp DESC, id DESC` ordering |
| Filter/search | `GET /events/evidence-vault?...` | Server-side query | 200; exact ID, camera, stream, decision, event type, and chain state confirmed |
| CSV export | `GET /events/evidence-vault/export` | Authenticated complete filtered CSV | 200; `text/csv`; full result, not only visible page |
| Media | `GET /events/{event_id}/evidence-image` | Protected evidence bytes | 200 authenticated, JPEG, non-zero bytes |
| Direct media | same endpoint without token | Denied | 401 |
| Verification | `POST /events/{event_id}/verify` | Authoritative independent results | 200; recomputed hash/signature and persisted chain classification displayed |
| Service health | `GET /health`, `GET /ready` | Healthy | 200 / 200 |

No Evidence Vault backend 500 was observed. The one browser-visible 404 was the expected stale pre-restart route response; Retry immediately succeeded after the evidence API backend was restarted. It is not a final-state failure.

# Database Cross-Check

At the final read-only snapshot, while the already-running camera workers continued live ingestion:

- Events: 5,981
- Evidence packages: 5,981
- Evidence-chain rows: 5,981
- Camera counts: `cam-border-01` 3,432; `cam-checkpoint-01` 2,549
- `PENDING`: 4,009, all with hash valid and signature valid, chain valid false
- `INVALID`: 1,972, all with hash valid and signature valid, chain valid false
- `VALID`: 0

The counts are timestamped rather than static because live evidence continued to arrive during the audit. Browser/API sampling covered both cameras, multiple streams, exact event-ID search, pending records, invalid records, and page boundaries. A direct API pagination check found zero duplicate event IDs between offsets 0 and 50. Two live rows were explicitly opened and their list/detail IDs remained consistent. The displayed media was fetched from the selected event's protected endpoint rather than a global or cached fallback.

# Content Hash Verification

The configured algorithm is SHA-256 over versioned canonical payload bytes. Current V1 packaging and backend verification use the shared canonicalization profile; the compatibility helper uses deterministic JSON with sorted keys and ASCII escaping. The backend recomputes the digest and compares it with `evidence_packages.sha256`. The UI consumes that backend result and never computes a competing JavaScript digest.

For the browser-verified invalid-chain sample, calculated and stored SHA-256 values matched exactly while chain state remained `INVALID`. This correctly proves that content-hash validity is independent from chain continuity. Stored hashes were not overwritten.

# Ed25519 Signature Verification

Evidence is signed by Ed25519 over the stored content-hash bytes. Backend verification resolves the exact signing `kid` (with explicit legacy resolution where supported) and invokes Ed25519 public-key verification. UI `VALID` now means the authoritative cryptographic check succeeded, not merely that a signature string exists. Signing key IDs are displayed; private key material is never returned or displayed.

# Chain Continuity

The authoritative chain is scoped by edge device/camera identity, with the signed `previous_hash` as the link authority. The verifier checks genesis rules, predecessor existence, predecessor hash, predecessor state, self-reference/cycles, and competing children/forks. Hash, signature, and chain results remain independent.

Live database truth was preserved: there were no chain-valid records at the final snapshot. The UI therefore makes no green full-chain claim. It shows `CHAIN PENDING` or `CHAIN BROKEN`, the exact stored `PENDING`/`INVALID` classification, previous hash, last verification time, and an overall “local integrity not fully verified” statement.

# Genesis

Controlled focused tests confirm a legitimate root without a previous hash is accepted only under the implemented same-source genesis rules. Multiple roots/ambiguous lineage are not silently treated as valid. No live historical record was rewritten to manufacture genesis.

# Fork/Cycle Detection

Disposable database fixtures confirm that `A→B` plus competing `A→C` rejects the fork without rewriting the accepted branch. Self-reference and a two-record cycle terminate safely and classify as invalid/pending-to-invalid according to the current verifier contract. No live evidence was changed for these tests.

# Legacy Evidence

Legacy `chain_status=NULL` is not automatically equated with tampering. The focused legacy fixture verifies continuity from available signed link information. The live demo snapshot contained only `PENDING` and `INVALID`, so the UI did not fabricate a separate legacy badge.

# Pending Verification

Out-of-order fixtures prove a missing predecessor stays pending and is re-evaluated when its predecessor arrives; multiple dependents heal in order only when cryptography is valid. Invalid hash/signature stops healing. Protected media retry remains bounded to ten attempts at three-second intervals and terminates with a synchronization-timeout explanation rather than an infinite spinner.

# External Anchor Status

The backend is running in `MOCK` blockchain mode because Fabric is unavailable on this host. The UI now separates local verification from external anchoring and displays `UNAVAILABLE (MOCK)`. Any mock transaction reference is labeled `LOCAL MOCK RECEIPT — NOT FABRIC ANCHORED`. No blockchain/Fabric verification is claimed.

# Media Security

- Authenticated representative JPEG: HTTP 200, non-zero size (sample 113,826 bytes).
- Unauthenticated direct evidence-media request: HTTP 401.
- Existing path traversal, key-segment containment, SHA-256 storage integrity, encryption, tamper, missing-file, and orphan-cleanup tests passed.
- Missing/unavailable evidence receives a precise UI state; another event's media is never silently substituted.

# Metadata Accuracy

List and detail views now expose authoritative event ID, camera ID, stream/session ID, event type, UTC capture timestamp, evidence-created timestamp, storage provider/status/size, schema version, crypto version, signing key ID, previous hash, and last-verified timestamp. Camera and stream filters are server-side, preventing cross-camera/session relabeling. Full SHA-256 values are selectable in detail; list abbreviations are limited to event IDs and do not masquerade as hashes.

# Problems Found

1. Vault completeness was limited to the newest 100 generic events.
2. Search and filters were client-only and inconsistent with the full database.
3. No authoritative total, deterministic pagination, loading/error/retry contract, or honest empty-filter detail clearing existed.
4. Signature presence was presented as signed/integrity state without cryptographic validity.
5. Hash, Ed25519 signature, local chain, and external anchor were not independently communicated.
6. Persisted chain status was hidden behind frontend-local verification state.
7. Mock ledger wording could be read as a real external blockchain anchor.
8. Export contained only the in-memory subset.
9. Forensic metadata and long hash layout were incomplete.
10. Unknown hash/signature values could render as invalid rather than unverified.

# Root Causes

- The page reused the generic WebSocket event cache (`limit=100`) instead of an evidence-package-backed listing contract.
- Filtering/export operated on frontend memory instead of server-side evidence queries.
- Row badges inferred integrity from field presence and frontend-local state.
- Evidence, chain, and external-anchor semantics were visually collapsed.
- Evidence-specific responsive and failure-state handling were incomplete.

# Fixes

- Added evidence-only paginated listing and complete filtered CSV export endpoints.
- Added stable secondary ordering and server-side search/filtering.
- Added evidence verification fields to the existing response schema and mapped persisted package state.
- Reworked only the Evidence Vault page to show independent hash/signature/chain/anchor truth, forensic metadata, loading/empty/error/retry states, and deterministic pagination.
- Added honest mock/Fabric wording and tri-state valid/invalid/unverified rendering.
- Added evidence-only narrow-desktop CSS and focused React tests.

# Browser Retest

The final live pass covered initial load, retry after backend restart, exact ID search, empty-result detail clearing, all five filters, combined camera+integrity filtering, Previous/Next navigation, multiple row selections, authenticated media, unauthenticated media denial, authoritative verification, export endpoint content, hard refresh, desktop layout, and 1050×800 narrow layout. No new fatal Evidence Vault console error appeared after the clean reload. Historical Vite hot-reload errors from the edit window and an earlier unrelated Dashboard upload error remain in the browser's retained log history; neither reproduced in the final Evidence Vault pass.

Screenshots:

- `artifacts/evidence_vault_final_audit_20260925/evidence_list.png`
- `artifacts/evidence_vault_final_audit_20260925/valid_evidence_detail.png`
- `artifacts/evidence_vault_final_audit_20260925/cryptographically_valid_chain_pending_detail.png`
- `artifacts/evidence_vault_final_audit_20260925/integrity_verification_detail.png`
- `artifacts/evidence_vault_final_audit_20260925/honest_broken_chain.png`
- `artifacts/evidence_vault_final_audit_20260925/narrow_viewport.png`

# Remaining Limitations

- No live demo record currently has `chain_status=VALID`; this is reported honestly and prevents claiming a fully valid live chain sample.
- The external Fabric anchor is unavailable; only local mock receipts exist.
- Live ingestion makes totals and newest-page membership change over time.
- The page uses in-place row detail rather than a separate detail route, so browser Back/Forward is not a list/detail navigation control. Hard refresh and repeated row selection are stable.
- The browser runtime did not surface a download event for the programmatic Blob link, but the visible export control produced no UI error and the same authenticated export endpoint was independently verified as HTTP 200, CSV, complete filtered content.

Focused evidence/security tests: 86 unique tests passed. The initial combined run had six setup errors caused solely by a stale pytest temp-directory ACL; those affected suites passed in a fresh isolated temp root. Frontend: 23/23 tests passed. Production frontend build passed (existing large-chunk advisory only).

Final module status: **WAITING FOR USER MANUAL EVIDENCE VAULT VERIFICATION**.
