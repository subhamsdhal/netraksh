"""Explicit, reviewable camera relationships for the SIH demonstration.

This is topology configuration, not identity matching. Production deployments
should replace/extend it from persisted camera adjacency data.
"""

CAMERA_RELATIONSHIPS = {
    "cam-border-01": {
        "cam-checkpoint-01": {"distance_m": 80.0, "expected_travel_time_s": 8.0, "tolerance_s": 8.0},
    },
    "cam-checkpoint-01": {
        "cam-border-01": {"distance_m": 80.0, "expected_travel_time_s": 8.0, "tolerance_s": 8.0},
    },
}


def related_camera_config(camera_id: str, other_camera_id: str):
    return CAMERA_RELATIONSHIPS.get(camera_id, {}).get(other_camera_id)
