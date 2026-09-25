"""
NETRAKSH — Blockchain client.
Implements the adapter pattern: production code uses get_blockchain_client()
and doesn't know whether it's talking to real Fabric or the mock.

Phase 0 result: WSL2 not available on this host. Docker cannot run.
Decision: MOCK adapter is the committed path for this build.
This is clearly labelled everywhere — in this code, in ARCHITECTURE.md,
in the dashboard UI (BLOCKCHAIN_MOCK_LABEL env var).

If Fabric becomes available later, replace MockBlockchainAdapter with
FabricCLIAdapter without touching any other code.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from backend.config import settings
from shared.schemas import AlertAcknowledgedTransaction, AlertIssuedTransaction

logger = logging.getLogger(__name__)


class BlockchainAdapter:
    """Abstract interface. Both real and mock implement this."""

    def submit_alert_issued(self, tx: AlertIssuedTransaction) -> dict:
        raise NotImplementedError

    def submit_alert_acknowledged(self, tx: AlertAcknowledgedTransaction) -> dict:
        raise NotImplementedError

    def query_alert(self, alert_id: str) -> Optional[dict]:
        raise NotImplementedError


class MockBlockchainAdapter(BlockchainAdapter):
    """
    Mock adapter that simulates network latency and returns a generated tx_id.
    Label: LEDGER: MOCK MODE (WSL2/Docker not available on this host).
    This is a temporary fallback for the demo environment only.
    """

    LABEL = "MOCK"

    def __init__(self):
        self._ledger: dict[str, dict] = {}
        logger.info(
            f"[LEDGER] Using MOCK adapter. "
            f"Reason: {settings.BLOCKCHAIN_MOCK_LABEL}"
        )

    def submit_alert_issued(self, tx: AlertIssuedTransaction) -> dict:
        tx_id = f"MOCK-{uuid.uuid4().hex[:16].upper()}"
        record = {
            "tx_id": tx_id,
            "type": "AlertIssued",
            "status": "MOCK",
            "alert_id": tx.alert_id,
            "evidence_package_hash": tx.evidence_package_hash,
            "severity": str(tx.severity),
            "zone_id": tx.zone_id,
            "issuing_command_id": tx.issuing_command_id,
            "timestamp": tx.timestamp.isoformat(),
            "submitted_at": datetime.utcnow().isoformat(),
            "label": self.LABEL,
        }
        self._ledger[tx.alert_id] = record
        logger.info(f"[LEDGER MOCK] AlertIssued: {json.dumps(record, indent=2)}")
        return {"tx_id": tx_id, "status": "MOCK"}

    def submit_alert_acknowledged(self, tx: AlertAcknowledgedTransaction) -> dict:
        tx_id = f"MOCK-{uuid.uuid4().hex[:16].upper()}"
        record = {
            "tx_id": tx_id,
            "type": "AlertAcknowledged",
            "status": "MOCK",
            "alert_id": tx.alert_id,
            "receiving_command_id": tx.receiving_command_id,
            "ack_timestamp": tx.ack_timestamp.isoformat(),
            "ack_status": tx.status,
            "submitted_at": datetime.utcnow().isoformat(),
            "label": self.LABEL,
        }
        self._ledger[f"ack-{tx.alert_id}"] = record
        logger.info(f"[LEDGER MOCK] AlertAcknowledged: {json.dumps(record, indent=2)}")
        return {"tx_id": tx_id, "status": "MOCK"}

    def query_alert(self, alert_id: str) -> Optional[dict]:
        return self._ledger.get(alert_id)


class FabricCLIAdapter(BlockchainAdapter):
    """
    HYPERLEDGER FABRIC adapter via peer chaincode CLI.
    Requires: peer binary on PATH, channel and chaincode configured in .env.
    This adapter is NOT activated in this build (WSL2/Docker unavailable).
    Left here so the path from mock → real Fabric is a one-line swap.
    """

    def __init__(self):
        self.peer_bin = settings.FABRIC_PEER_BIN
        self.channel = settings.FABRIC_CHANNEL
        self.chaincode = settings.FABRIC_CHAINCODE
        self.org_msp = settings.FABRIC_ORG_MSP
        logger.info(f"[BLOCKCHAIN] Fabric CLI adapter initialized (channel={self.channel})")

    def _invoke(self, function: str, args: list) -> str:
        import subprocess
        cmd = [
            self.peer_bin, "chaincode", "invoke",
            "-C", self.channel,
            "-n", self.chaincode,
            "-c", json.dumps({"function": function, "Args": args}),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"peer chaincode invoke failed: {result.stderr}")
        return result.stdout

    def submit_alert_issued(self, tx: AlertIssuedTransaction) -> dict:
        args = [
            tx.alert_id,
            tx.evidence_package_hash,
            str(tx.severity),
            tx.zone_id,
            tx.issuing_command_id,
            tx.timestamp.isoformat(),
        ]
        output = self._invoke("AlertIssued", args)
        # NOT EXERCISED: this adapter has never been run against a real
        # Fabric network (WSL2/Docker unavailable in this dev environment --
        # see docs/LIMITATIONS.md). `peer chaincode invoke`'s real stdout is
        # logged here rather than silently discarded, so the first real run
        # against an actual network is debuggable; tx_id below is a locally
        # generated placeholder, not parsed from a real chaincode response
        # (whose exact output format/whether it even contains a usable tx id
        # has not been verified against a live network).
        logger.debug(f"[BLOCKCHAIN FABRIC] peer chaincode invoke raw output: {output!r}")
        tx_id = f"FABRIC-{uuid.uuid4().hex[:16].upper()}"
        logger.info(f"[BLOCKCHAIN FABRIC] AlertIssued: tx_id={tx_id}")
        return {"tx_id": tx_id, "status": "CONFIRMED"}

    def submit_alert_acknowledged(self, tx: AlertAcknowledgedTransaction) -> dict:
        args = [
            tx.alert_id,
            tx.receiving_command_id,
            tx.ack_timestamp.isoformat(),
            tx.status,
            tx.signature,
        ]
        output = self._invoke("AlertAcknowledged", args)
        # See the identical note in submit_alert_issued() above: not
        # exercised against a real network, real output logged rather than
        # discarded, tx_id is a local placeholder.
        logger.debug(f"[BLOCKCHAIN FABRIC] peer chaincode invoke raw output: {output!r}")
        tx_id = f"FABRIC-{uuid.uuid4().hex[:16].upper()}"
        logger.info(f"[BLOCKCHAIN FABRIC] AlertAcknowledged: tx_id={tx_id}")
        return {"tx_id": tx_id, "status": "CONFIRMED"}

    def query_alert(self, alert_id: str) -> Optional[dict]:
        import subprocess
        cmd = [
            self.peer_bin, "chaincode", "query",
            "-C", self.channel,
            "-n", self.chaincode,
            "-c", json.dumps({"function": "QueryAlert", "Args": [alert_id]}),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Factory — the only entry point for blockchain operations
# ---------------------------------------------------------------------------
_client: Optional[BlockchainAdapter] = None


def get_blockchain_client() -> BlockchainAdapter:
    """
    Returns the configured blockchain adapter.
    Mode is set by BLOCKCHAIN_MODE env var: "mock" | "fabric".
    The core system continues running even if this function is never called
    (escalation failure is non-fatal by design, §37 of architecture).
    """
    global _client
    if _client is None:
        if settings.BLOCKCHAIN_MODE == "fabric":
            try:
                _client = FabricCLIAdapter()
            except Exception as exc:
                logger.error(f"Fabric adapter init failed ({exc}), falling back to mock")
                _client = MockBlockchainAdapter()
        else:
            _client = MockBlockchainAdapter()
    return _client
