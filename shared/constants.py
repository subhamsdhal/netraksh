"""
NETRAKSH — Shared constants.
All enumerations are defined exactly once here and imported by both edge and backend.
"""
from enum import Enum


class CameraHealthState(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"

class ErrorCategory(str, Enum):
    NETWORK_TRANSIENT = "NETWORK_TRANSIENT"
    BACKEND_5XX = "BACKEND_5XX"
    BACKEND_4XX = "BACKEND_4XX"
    AUTH_FAILURE = "AUTH_FAILURE"
    DATABASE_ERROR = "DATABASE_ERROR"
    CAMERA_READ_ERROR = "CAMERA_READ_ERROR"
    MODEL_ERROR = "MODEL_ERROR"
    EVIDENCE_ERROR = "EVIDENCE_ERROR"
    CRYPTO_VERIFICATION_ERROR = "CRYPTO_VERIFICATION_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    UNKNOWN = "UNKNOWN"


class SceneCondition(str, Enum):
    CLEAR_DAY = "CLEAR_DAY"
    LOW_LIGHT_NIGHT = "LOW_LIGHT_NIGHT"
    FOG_RAIN = "FOG_RAIN"
    GLARE = "GLARE"


class DecisionState(str, Enum):
    DETECTED = "DETECTED"
    UNCERTAIN = "UNCERTAIN"
    ABSTAIN = "ABSTAIN"


class EventState(str, Enum):
    """
    Event verification lifecycle (architecture v4 §9 — Temporal Event Verification).
    A task module firing only reaches OBSERVED/CANDIDATE; evidence is packaged
    and an alert raised only once a candidate is promoted to VERIFIED/ALERTED
    by edge.temporal.event_verifier.EventVerifier. ACKNOWLEDGED/CLOSED are set
    later by real command-center operator action: backend/api/alerts.py's
    POST /alerts/{id}/acknowledge and POST /alerts/{id}/close set
    Alert.lifecycle_state to these real values (SIH PS 26187 audit finding
    fixed — CLOSED previously had zero real producer anywhere, confirmed by
    grep, not just this docstring's own claim).
    """
    OBSERVED = "OBSERVED"
    CANDIDATE = "CANDIDATE"
    VERIFIED = "VERIFIED"
    ALERTED = "ALERTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLOSED = "CLOSED"


class EventType(str, Enum):
    VIRTUAL_FENCE_CROSSING = "VIRTUAL_FENCE_CROSSING"
    LINE_CROSSING = "LINE_CROSSING"
    LOITERING = "LOITERING"
    ABANDONED_OBJECT = "ABANDONED_OBJECT"
    WRONG_DIRECTION = "WRONG_DIRECTION"
    ANPR_READ = "ANPR_READ"
    FACE_DETECTED = "FACE_DETECTED"
    CAMERA_HEALTH_CHANGE = "CAMERA_HEALTH_CHANGE"
    MOVEMENT_UNCLASSIFIED = "MOVEMENT_UNCLASSIFIED"
    RAPID_APPROACH_TO_BOUNDARY = "RAPID_APPROACH_TO_BOUNDARY"
    REPEATED_ZONE_CROSSING = "REPEATED_ZONE_CROSSING"
    SUSTAINED_DIRECTION_VIOLATION = "SUSTAINED_DIRECTION_VIOLATION"


class DetectionClass(str, Enum):
    PERSON = "person"
    VEHICLE = "vehicle"
    FACE = "face"
    LICENSE_PLATE = "license_plate"
    UNKNOWN = "unknown"


class VehicleSubtype(str, Enum):
    """
    Real sub-classification within DetectionClass.VEHICLE — SIH problem
    statement 26187 asks for "vehicle detection AND classification", not
    detection alone. YOLOv8n's own COCO classes already distinguish these
    (edge/detection/detector.py's _YOLO_CLASS_MAP previously discarded that
    distinction, collapsing car/motorcycle/bus/truck into one generic
    "vehicle" DetectionClass everywhere). This is a real, additive field
    alongside detection_class, not a replacement for it — every existing
    piece of gating logic that checks `detection_class == VEHICLE`
    (ANPRModule, cross-camera corroboration class matching, etc.) is
    unaffected; this only adds a real answer to "what kind of vehicle".
    """
    CAR = "car"
    MOTORCYCLE = "motorcycle"
    BUS = "bus"
    TRUCK = "truck"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class FenceDirection(str, Enum):
    OUTSIDE_TO_RESTRICTED = "OUTSIDE_TO_RESTRICTED"
    RESTRICTED_TO_OUTSIDE = "RESTRICTED_TO_OUTSIDE"
    UNKNOWN = "UNKNOWN"


class LineCrossingDirection(str, Enum):
    """
    A line has no natural "inside"/"outside" the way a fence polygon does, so
    direction is reported relative to the order of the two configured points
    (A = polygon.points[0], B = polygon.points[1]): A_TO_B means the track
    crossed from the side where cross((B-A),(P-A)) > 0 to the side where it's
    < 0; B_TO_A is the reverse. See edge/rules/modules.py::LineCrossingModule.
    """
    A_TO_B = "A_TO_B"
    B_TO_A = "B_TO_A"


class ZoneType(str, Enum):
    FENCE = "fence"
    CHECKPOINT = "checkpoint"
    VERIFICATION = "verification"
    BOUNDARY = "boundary"


class UserRole(str, Enum):
    ADMIN = "ADMIN"
    OPERATOR = "OPERATOR"
    AUDITOR = "AUDITOR"


class BlockchainStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    MOCK = "MOCK"


class SyncStatus(str, Enum):
    QUEUED = "QUEUED"
    SYNCING = "SYNCING"
    SYNCED = "SYNCED"
    FAILED = "FAILED"


class VerificationResult(str, Enum):
    HASH_VALID = "HASH_VALID"
    HASH_FAILED = "HASH_FAILED"
    SIGNATURE_VALID = "SIGNATURE_VALID"
    SIGNATURE_FAILED = "SIGNATURE_FAILED"
    CHAIN_VALID = "CHAIN_VALID"
    CHAIN_BROKEN = "CHAIN_BROKEN"


# Health reason codes
class HealthReason(str, Enum):
    OK = "ok"
    FROZEN_STREAM = "frozen_stream"
    EXCESSIVE_BLUR = "excessive_blur"
    ABNORMAL_EXPOSURE = "abnormal_exposure"
    FPS_DEGRADED = "fps_degraded"
    CLOCK_DRIFT = "clock_drift"
    STREAM_UNAVAILABLE = "stream_unavailable"
    LOW_LIGHT = "low_light"
    STREAM_STALLED = "stream_stalled"
    STREAM_RECONNECTING = "stream_reconnecting"

class StreamState(str, Enum):
    INITIALIZING = "INITIALIZING"
    CONNECTED = "CONNECTED"
    STALLING = "STALLING"
    RECONNECTING = "RECONNECTING"
    FAILED = "FAILED"
    STOPPED = "STOPPED"



# Calibration threshold keys (match SceneCondition values)
CONDITION_THRESHOLD_KEYS = {
    SceneCondition.CLEAR_DAY: "THRESHOLD_CLEAR_DAY",
    SceneCondition.LOW_LIGHT_NIGHT: "THRESHOLD_LOW_LIGHT_NIGHT",
    SceneCondition.FOG_RAIN: "THRESHOLD_FOG_RAIN",
    SceneCondition.GLARE: "THRESHOLD_GLARE",
}

# Severity escalation threshold for blockchain submission
ESCALATION_SEVERITY_THRESHOLD = Severity.HIGH

# Loitering dwell time (seconds) before alert fires
LOITERING_DWELL_SECONDS = 15.0

# Abandoned object: frames track must be stationary then disappear
ABANDONED_STATIONARY_FRAMES = 60
ABANDONED_DISAPPEAR_FRAMES = 5

# Frozen frame detection: variance below this = frozen
FROZEN_FRAME_VARIANCE_THRESHOLD = 2.0

# Adaptive Compute Gating (architecture v4 §6). Deliberately higher than
# FROZEN_FRAME_VARIANCE_THRESHOLD above: this distinguishes "no real motion,
# just sensor noise" (skip full YOLO inference to save compute) from "frozen/
# dead stream" (Gate 1 already handles that as FAILED before this is ever
# checked, so a frame that reaches this point is guaranteed not frozen).
MOTION_GATE_VARIANCE_THRESHOLD = 15.0

# How many frames to skip between full-inference passes while genuinely idle
# (no motion AND no active tracks AND no pending candidate events).
IDLE_INFERENCE_INTERVAL_FRAMES = 5

# Night-motion fallback (architecture v4 §3): minimum seconds between
# consecutive MOVEMENT_UNCLASSIFIED evidence emissions while motion persists,
# so a continuously-moving unclassified object doesn't flood evidence
# storage with a new snapshot every frame.
NIGHT_MOTION_COOLDOWN_SECONDS = 30.0

# Tiered evidence capture by condition quality: a FAILED-camera-health
# ABSTAIN heartbeat previously saved no visual evidence at all (frame=None,
# every frame, unconditionally) -- so if the camera health monitor itself
# had a false trigger, there was no way to review what the camera actually
# saw. It's still emitted every frame (unchanged -- that heartbeat cadence
# is itself real, useful camera-health telemetry), but the raw encrypted
# snapshot is now captured periodically at this interval instead of never,
# so a sustained outage doesn't flood local disk with one encrypted JPEG
# per frame either.
ABSTAIN_SNAPSHOT_INTERVAL_SECONDS = 30.0

# Blur detection: Laplacian variance below this = blurry
BLUR_LAPLACIAN_THRESHOLD = 80.0

# Exposure: histogram clipping fraction above this = over/under exposed
EXPOSURE_CLIPPING_THRESHOLD = 0.10

# FPS degradation: ratio below this triggers DEGRADED
FPS_DEGRADED_RATIO = 0.70

# Timestamp drift: seconds above this triggers DEGRADED
CLOCK_DRIFT_DEGRADED_SECONDS = 5.0
CLOCK_DRIFT_FAILED_SECONDS = 30.0

# Condition classification thresholds (OpenCV heuristics)
# Brightness (mean pixel 0-255)
BRIGHTNESS_NIGHT_THRESHOLD = 60
BRIGHTNESS_GLARE_THRESHOLD = 220

# Fog: local std dev below this = low contrast / foggy
FOG_CONTRAST_THRESHOLD = 30.0
