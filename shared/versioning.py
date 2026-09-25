import json
from datetime import datetime
from typing import Dict, Any

class UnsupportedProfileError(Exception):
    pass

class PartialVersionMetadataError(Exception):
    pass

SCHEMA_VERSION_V1: str = "1.0"
CRYPTO_VERSION_V1: str = "crypto-v1"
PROFILE_LEGACY_V0: str = "legacy-v0"

LEGACY_V0_SIGNABLE_FIELDS: tuple = (
    "event_id",
    "camera_id",
    "timestamp",
    "zone_id",
    "detection_class",
    "confidence",
    "scene_condition",
    "camera_health_state",
    "decision_state",
    "evidence_clip_ref",
    "previous_hash",
)

CRYPTO_V1_SIGNABLE_FIELDS: tuple = (
    "schema_version",
    "crypto_version",
    "event_id",
    "camera_id",
    "timestamp",
    "zone_id",
    "detection_class",
    "confidence",
    "scene_condition",
    "camera_health_state",
    "decision_state",
    "evidence_clip_ref",
    "previous_hash",
)

def extract_signable_dict(envelope_dict: Dict[str, Any], profile_id: str) -> Dict[str, Any]:
    if profile_id == "legacy-v0":
        fields = LEGACY_V0_SIGNABLE_FIELDS
    elif profile_id == "crypto-v1":
        fields = CRYPTO_V1_SIGNABLE_FIELDS
    else:
        raise UnsupportedProfileError(f"Unknown profile: {profile_id!r}")
        
    result = {}
    for f in fields:
        val = envelope_dict.get(f)
        if val is None:
            result[f] = ""
        elif isinstance(val, datetime):
            result[f] = val.isoformat()
        else:
            if f in ("detection_class", "scene_condition", "camera_health_state", "decision_state") and not isinstance(val, str):
                result[f] = str(val)
            else:
                result[f] = val
    return result

def detect_profile(envelope_dict: Dict[str, Any]) -> str:
    schema = envelope_dict.get("schema_version")
    crypto = envelope_dict.get("crypto_version")
    
    if schema is None and crypto is None:
        return "legacy-v0"
    if schema is not None and crypto is not None:
        return crypto
    
    raise PartialVersionMetadataError("Partial version metadata detected. schema_version and crypto_version must both be present or both absent.")

def canonicalize(envelope_dict: Dict[str, Any], profile_id: str) -> bytes:
    fields = extract_signable_dict(envelope_dict, profile_id)
    # The pre-phase-8.4 code uses: json.dumps(fields, sort_keys=True, ensure_ascii=True)
    # We MUST preserve this exact behavior for legacy-v0. The spec says "without spaces around separators",
    # but Python's default is `(', ', ': ')`. To match existing behavior we use the exact arguments.
    serialized = json.dumps(fields, sort_keys=True, ensure_ascii=True)
    return serialized.encode("utf-8")

from enum import Enum
from dataclasses import dataclass
from types import MappingProxyType

class CryptoProfileStatus(Enum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    RETIRED = "RETIRED"
    UNSUPPORTED = "UNSUPPORTED"

@dataclass(frozen=True)
class CryptoProfile:
    profile_id: str
    hash_algorithm: str
    signature_algorithm: str
    serialization: str
    signature_input: str
    signable_fields: tuple
    status: CryptoProfileStatus

_PROFILE_LEGACY_V0 = CryptoProfile(
    profile_id="legacy-v0",
    hash_algorithm="SHA-256",
    signature_algorithm="Ed25519",
    serialization="JSON(sort_keys=True, ensure_ascii=True, UTF-8)",
    signature_input="hex-string-bytes",
    signable_fields=LEGACY_V0_SIGNABLE_FIELDS,
    status=CryptoProfileStatus.ACTIVE,
)

_PROFILE_CRYPTO_V1 = CryptoProfile(
    profile_id="crypto-v1",
    hash_algorithm="SHA-256",
    signature_algorithm="Ed25519",
    serialization="JSON(sort_keys=True, ensure_ascii=True, UTF-8)",
    signature_input="hex-string-bytes",
    signable_fields=CRYPTO_V1_SIGNABLE_FIELDS,
    status=CryptoProfileStatus.ACTIVE,
)

CRYPTO_REGISTRY = MappingProxyType({
    "legacy-v0": _PROFILE_LEGACY_V0,
    "crypto-v1": _PROFILE_CRYPTO_V1,
})

def lookup_profile(profile_id: str) -> CryptoProfile:
    profile = CRYPTO_REGISTRY.get(profile_id)
    if profile is None:
        raise UnsupportedProfileError(f"Unknown profile: {profile_id!r}")
    if profile.status == CryptoProfileStatus.UNSUPPORTED:
        raise UnsupportedProfileError(f"Profile {profile_id!r} is marked UNSUPPORTED")
    return profile

