"""
NETRAKSH Edge — Event Verification State Machine (Layer 4.5 / Priority 3).
Implements the EXACT lifecycle specified in architecture v4 §9 (locked):

    OBSERVED -> CANDIDATE -> [held while UNCERTAIN] -> VERIFIED -> ALERTED
                                                       -> ACKNOWLEDGED -> CLOSED

Design intent (from the architecture doc, do not deviate silently):
  - CANDIDATE: a task module (fence/loitering/abandoned/ANPR/face) fires once.
    Evidence is NOT packaged and no alert is raised yet.
  - A candidate accumulates one "confirmation" on every subsequent frame where
    the SAME condition is observed again for the SAME key AND the accompanying
    Reliability decision (edge.reliability.decision) for that frame is DETECTED.
  - A frame where the condition still holds but Reliability says UNCERTAIN does
    NOT count as a confirmation, but it does NOT reset progress either — the
    candidate is held pending, exactly as architecture v4 §9 specifies
    ("the candidate is held, not discarded, and re-evaluated on subsequent
    frames"). This is what prevents fog/night/degraded-camera moments from
    either (a) silently vanishing a real event, or (b) forcing a low-confidence
    frame to count as if it were solid evidence.
  - Once confirm_count reaches the event type's required_confirmations, the
    candidate is promoted straight to VERIFIED -> ALERTED in the same call,
    and the caller (edge/main.py) packages evidence for exactly that frame.
  - A candidate not reconfirmed at all within max_gap_frames expires with NO
    evidence generated. This — combined with the confirmation requirement
    above — is the concrete mechanism behind the project's stated thesis:
    a single noisy frame cannot become a security alert.

Different event types need different confirmation depth:
  - Zone/fence crossing (and line crossing, once built) are edge-triggered on
    a single frame transition, so they are the type most exposed to one-frame
    tracking jitter -- default requires multiple consecutive confirmations.
  - Loitering and abandoned-object already require sustained dwell/stationary
    time *inside their own task module* before they ever fire a candidate in
    the first place (see edge/rules/modules.py), so their temporal persistence
    is already baked in -- default requires only 1 confirmation (auto-verify
    on first candidate), so we do not double-gate and delay a real alert for
    no reason. ANPR/face-detection results are single-shot reads, not a
    condition that persists across frames, so they default to 1 as well.

This module is a pure in-memory state tracker with no I/O and no side effects
beyond its own state, deliberately structured the same way as
edge/reliability/decision.py so it is unit-testable the same way.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from shared.constants import EventState

logger = logging.getLogger(__name__)

# Confirmations required (of the SAME candidate, on SEPARATE frames) before
# promotion to VERIFIED. Keys are EventType.<X>.value strings.
DEFAULT_REQUIRED_CONFIRMATIONS: Dict[str, int] = {
    # Transition events are re-confirmed by EdgePipeline while the tracked
    # object remains on the new side.  Two observations reject one-frame
    # tracker jitter without delaying a real crossing materially.
    "VIRTUAL_FENCE_CROSSING": 2,
    "LINE_CROSSING": 2,
    "LOITERING": 1,
    "ABANDONED_OBJECT": 1,
    # OCR and face detections recur while their track remains in the relevant
    # zone; require temporal confirmation before forensic evidence is emitted.
    "ANPR_READ": 2,
    "FACE_DETECTED": 2,
    # The night-motion module already applies frame differencing and its own
    # cooldown.  It has no persistent classified track to re-confirm against.
    "MOVEMENT_UNCLASSIFIED": 1,
}

# A CANDIDATE not reconfirmed at all (condition simply stops recurring) within
# this many frames expires with no evidence generated.
DEFAULT_MAX_GAP_FRAMES = 5

# After ALERTED, suppress re-alerting the identical key for this long, so a
# condition that keeps being true every frame doesn't spam duplicate alerts.
DEFAULT_COOLDOWN_SECONDS = 30.0


@dataclass
class _PendingCandidate:
    event_type: str
    payload: dict
    confirm_count: int = 0
    last_seen_frame: int = 0
    state: str = EventState.CANDIDATE.value
    alerted_at: Optional[float] = None


class EventVerifier:
    """
    Tracks one lifecycle state machine per (camera_id, track_id, event_type,
    zone_id) key. `observe()` is called by the pipeline whenever a task
    module's candidate condition is true for a key on the current frame;
    `expire_stale()` is called once per frame to age out anything that was
    not reconfirmed.
    """

    def __init__(
        self,
        required_confirmations: Optional[Dict[str, int]] = None,
        max_gap_frames: int = DEFAULT_MAX_GAP_FRAMES,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    ):
        self._required = dict(DEFAULT_REQUIRED_CONFIRMATIONS)
        if required_confirmations:
            self._required.update(required_confirmations)
        self._max_gap_frames = max_gap_frames
        self._cooldown_seconds = cooldown_seconds
        self._pending: Dict[str, _PendingCandidate] = {}

    @staticmethod
    def make_key(camera_id: str, track_id: Optional[int], event_type: str, zone_id: str) -> str:
        return f"{camera_id}:{track_id}:{event_type}:{zone_id}"

    def observe(
        self,
        key: str,
        event_type: str,
        payload: dict,
        frame_count: int,
        reliability_is_detected: bool,
    ) -> Tuple[str, Optional[dict]]:
        """
        Register that `event_type`'s candidate condition is true again this
        frame for `key`.

        Returns (current_state, verified_payload). `verified_payload` is
        non-None ONLY on the single frame `key` is promoted to VERIFIED —
        the caller must package evidence and raise the alert exactly then,
        and must not do so on any other call.
        """
        required = self._required.get(event_type, 1)
        existing = self._pending.get(key)

        if existing is None:
            existing = _PendingCandidate(event_type=event_type, payload=payload)
            self._pending[key] = existing
            logger.debug(f"[Verifier] {key}: OBSERVED -> CANDIDATE (requires {required} confirmation(s))")

        existing.last_seen_frame = frame_count

        # Cooldown: an already-ALERTED key doesn't reopen immediately just
        # because the same condition is still true a few frames later.
        if existing.state == EventState.ALERTED.value:
            if existing.alerted_at is not None and (time.time() - existing.alerted_at) < self._cooldown_seconds:
                return existing.state, None
            # Cooldown elapsed — this is a genuinely new episode of the condition.
            existing.state = EventState.CANDIDATE.value
            existing.confirm_count = 0
            existing.alerted_at = None
            logger.debug(f"[Verifier] {key}: cooldown elapsed, reopened as fresh CANDIDATE")

        existing.payload = payload  # always keep the freshest evidence-relevant payload

        if not reliability_is_detected:
            # Held, not discarded, and not counted as progress either
            # (architecture v4 §9: "the candidate is held ... and re-evaluated").
            logger.debug(
                f"[Verifier] {key}: held (reliability UNCERTAIN this frame, "
                f"{existing.confirm_count}/{required} confirmations so far)"
            )
            return existing.state, None

        existing.confirm_count += 1

        if existing.confirm_count >= required:
            verified_payload = dict(existing.payload)
            existing.state = EventState.ALERTED.value
            existing.alerted_at = time.time()
            logger.info(
                f"[Verifier] {key}: CANDIDATE -> VERIFIED -> ALERTED "
                f"({existing.confirm_count}/{required} confirmations)"
            )
            return existing.state, verified_payload

        logger.debug(
            f"[Verifier] {key}: CANDIDATE holding ({existing.confirm_count}/{required} confirmations)"
        )
        return existing.state, None

    def expire_stale(self, current_frame: int) -> List[str]:
        """
        Drop any CANDIDATE (not yet ALERTED) not reconfirmed within
        max_gap_frames. Returns the list of expired keys (for logging/tests).
        This is the concrete mechanism that stops a single noisy frame — or a
        track that flickers and vanishes — from ever becoming an alert.
        """
        stale = [
            k for k, v in self._pending.items()
            if v.state == EventState.CANDIDATE.value
            and (current_frame - v.last_seen_frame) > self._max_gap_frames
        ]
        for k in stale:
            logger.debug(
                f"[Verifier] {k}: CANDIDATE expired "
                f"(no reconfirmation within {self._max_gap_frames} frames)"
            )
            del self._pending[k]
        return stale

    def get_pending_by_type(self, event_type: str) -> List[Tuple[str, dict]]:
        """Keys currently sitting in CANDIDATE state for a given event type."""
        return [
            (k, v.payload) for k, v in self._pending.items()
            if v.event_type == event_type and v.state == EventState.CANDIDATE.value
        ]

    def get_state(self, key: str) -> Optional[str]:
        p = self._pending.get(key)
        return p.state if p else None

    def get_pending_count(self) -> int:
        return len(self._pending)
