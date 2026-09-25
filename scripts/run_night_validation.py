"""Bounded real EdgePipeline low-light validation on repository-owned footage.

Frames are darkened in memory only; the source video and forensic evidence
remain untouched. Results validate pipeline routing and noise gating, not real
night recognition accuracy.
"""
from pathlib import Path
import json
import tempfile
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edge.main import EdgePipeline
from edge.evidence.packager import EdgeKeyManager


def run_variant(root: Path, label: str, factor: float, limit: int = 24) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"netraksh-night-{label}-", ignore_cleanup_errors=True) as temp:
        temp_path = Path(temp)
        camera_id = f"night-{label}"
        config = {
            "camera_id": camera_id,
            "video_source": str(root / "demo/videos/vtest.avi"),
            "zones_config_path": str(root / "demo/scripts/zones_config.json"),
            "key_dir": str(temp_path / "certs"),
            "chain_db_path": str(temp_path / "chain.db"),
            "sync_db_path": str(temp_path / "sync.db"),
            "clip_dir": str(temp_path / "clips"),
            "backend_url": "http://127.0.0.1:59999",
        }
        key = EdgeKeyManager(
            private_key_path=str(temp_path / "certs" / f"{camera_id}.key"),
            public_key_path=str(temp_path / "certs" / f"{camera_id}.pub"),
        )
        key.load_or_generate(allow_generate=True)
        pipeline = EdgePipeline(config)
        pipeline.detector.load()
        frames = 0
        try:
            for source_frame, meta in pipeline.adapter.frames():
                frame = np.clip(source_frame.astype(np.float32) * factor, 0, 255).astype(np.uint8)
                pipeline._process_frame(frame, meta)
                frames += 1
                if frames >= limit:
                    break
        finally:
            pipeline.adapter.stop()
            pipeline.adapter.join()
        records = pipeline.chain_store.get_all_records()
        events = []
        for record in records:
            payload = record.get("package", record) if isinstance(record, dict) else {}
            if payload.get("event_type"):
                events.append({k: payload.get(k) for k in (
                    "event_type", "scene_condition", "lighting_state", "mean_luminance",
                    "enhancement_applied", "detection_method", "motion_area",
                    "motion_persistence", "decision_state", "severity")})
        return {"sample_id": label, "factor": factor, "frames": frames,
                "events": events, "evidence_records": len(records),
                "metrics": pipeline.metrics.summary()}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    results = [
        run_variant(root, "daylight", 1.0),
        run_variant(root, "low-light", 0.32),
        run_variant(root, "very-low-light", 0.08),
        run_variant(root, "near-black", 0.01),
    ]
    print(json.dumps({"controlled_transform": True, "results": results}, default=str))


if __name__ == "__main__":
    main()
