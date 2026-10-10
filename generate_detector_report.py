"""Build a detector comparison report from measured benchmark artifacts only.

This is a documentation utility, not part of the inference runtime.  Missing
artifacts fail closed so a report cannot accidentally present invented metrics.
"""

import json
from pathlib import Path


_ARTIFACTS = ("docs/yolov8n_vtest.json", "docs/yolov8n_demo.json")


def generate_report(mock_fs=None):
    exists = mock_fs["exists"] if mock_fs is not None else lambda path: Path(path).exists()
    read = mock_fs["read"] if mock_fs is not None else lambda path: json.loads(Path(path).read_text(encoding="utf-8"))

    if not all(exists(path) for path in _ARTIFACTS):
        raise SystemExit("Detector benchmark artifacts are missing; refusing to generate a report")

    measurements = [(path, read(path)) for path in _ARTIFACTS]
    if any(not isinstance(data, dict) for _, data in measurements):
        raise SystemExit("Detector benchmark artifacts must contain JSON objects")

    lines = ["# Detector comparison", "", "YOLOv8n: **BENCHMARKED**"]
    if exists("yolov8s.pt"):
        lines.append("YOLOv8s: WEIGHT AVAILABLE; NOT BENCHMARKED without measured results")
    else:
        lines.extend((
            "YOLOv8s: **NOT BENCHMARKED**",
            "Candidate weight yolov8s.pt was not available locally. No download was attempted.",
        ))

    for path, data in measurements:
        lines.extend((
            "", f"## {path}",
            f"Hardware: {data.get('hardware', 'NOT MEASURED')}",
            f"Confidence threshold: {data.get('config', {}).get('confidence_threshold', 'NOT MEASURED')}",
            f"Latency samples (seconds): {data.get('latency', {}).get('end_to_end', 'NOT MEASURED')}",
            f"Peak RSS: {data.get('memory', {}).get('rss_during_peak', 'NOT MEASURED')}",
            f"Detected objects: {data.get('counts', {}).get('objects_detected', 'NOT MEASURED')}",
            f"Tracks created: {data.get('tracking', {}).get('tracks_created', 'NOT MEASURED')}",
            f"Tracks terminated: {data.get('tracking', {}).get('tracks_terminated', 'NOT MEASURED')}",
            f"Continuity interventions: {data.get('tracking', {}).get('continuity_interventions', 'NOT MEASURED')} "
            "(TRACK FRAGMENTATION / REASSOCIATION PROXY, NOT ID SWITCH COUNT)",
            f"Pixel-area size bins: {data.get('pixel_area_distribution', 'NOT MEASURED')}",
        ))

    lines.extend((
        "", "## Limits", "**Precision**: NOT MEASURABLE", "**Recall**: NOT MEASURABLE",
        "**F1**: NOT MEASURABLE", "**mAP**: NOT MEASURABLE",
        "Pixel-area categories are merely size bins, NOT real-world distance categories.",
        "YOLOv8n remains the current default.",
        "This is NOT a result proving YOLOv8n is superior to YOLOv8s.",
    ))
    return "\n".join(lines) + "\n"
