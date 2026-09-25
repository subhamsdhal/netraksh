# SIH 26187 — Evidence Chain Continuity Validation

## Scope and result

The Evidence Vault defect was reproduced against the native two-camera demo.
The server was deriving continuity from `sequence_number - 1`, so an historic
server-ledger gap left later, hash-valid and signature-valid packages marked
`PENDING`/broken.  Verification now uses the signed `previous_hash` within the
authenticated camera scope; sequence is retained only as a legacy splice guard.

The Evidence Vault browser check completed after the verifier was changed to
walk a source chain with one scoped database read rather than one query per
historical link.

## Root cause and compatible reconstruction

- Camera 1 had five missing server-chain metadata rows: sequences 2183–2187.
- Camera 2 had 126 missing server-chain metadata rows when applied (the edge
  worker continued producing evidence between dry-run and apply).
- The append-only local edge ledgers contained each missing signed hash/link.
- `scripts/reconcile_evidence_chain.py` validated contiguity, both surrounding
  server links, and each recovered Ed25519 signature against exactly one
  registered camera key before inserting metadata only.
- Recovered rows are explicitly `LEGACY_ANCHORED`.  They do not claim that a
  missing historical full payload was recreated or re-hashed by the server.

No evidence payload, event, hash, signature, or pre-existing ledger row was
modified.

## Current safety boundary

The operator explicitly authorized the narrow revalidation. It re-queued only
rows whose stored hash and Ed25519 signature were already valid, then resolved
their descendants from the `LEGACY_ANCHORED` rows. Genuine remaining invalid
segments were not re-queued. The live two-camera database still contains
downstream `PENDING` records after those invalid segments, so the newest sample
can correctly remain BROKEN.

Accordingly, this report is **not a code-freeze closure**: continuity is now
correctly classified, but the live ledger still has genuine invalid segments
that require operator investigation rather than automatic repair. Genuine
malformed, forked, cyclic, or bad-signature records remain INVALID.

## Automated verification

`pytest tests/unit/test_deferred_verification.py tests/unit/test_evidence.py
tests/test_hash_chain.py -q --basetemp artifacts\\pytest-evidence-chain-final`
passed: **42 passed**.

Coverage includes normal and out-of-order delivery, non-contiguous transport
sequence, per-camera isolation, legacy-null compatibility, invalid predecessor,
tamper detection, fork rejection, and self/two-record cycle rejection.
