"""Bounded real-input ANPR smoke run for SIH validation.

Uses the actual EdgePipeline and repository-owned vtest footage. It reports
what the pipeline produced; it never fabricates a plate when the clip has no
readable plate.
"""
from pathlib import Path
import json
import tempfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edge.main import EdgePipeline
from edge.evidence.packager import EdgeKeyManager


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="netraksh-anpr-", ignore_cleanup_errors=True) as temp:
        temp_path = Path(temp)
        config = {
            "camera_id": "anpr-real-input-cam",
            "video_source": str(root / "demo/videos/vtest.avi"),
            "zones_config_path": str(root / "demo/scripts/zones_config.json"),
            "key_dir": str(temp_path / "certs"),
            "chain_db_path": str(temp_path / "chain.db"),
            "sync_db_path": str(temp_path / "sync.db"),
            "clip_dir": str(temp_path / "clips"),
            "backend_url": "http://127.0.0.1:59999",
        }
        key_manager = EdgeKeyManager(
            private_key_path=str(temp_path / "certs" / "anpr-real-input-cam.key"),
            public_key_path=str(temp_path / "certs" / "anpr-real-input-cam.pub"),
        )
        key_manager.load_or_generate(allow_generate=True)
        pipeline = EdgePipeline(config)
        pipeline.detector.load()
        frames = 0
        try:
            for frame, meta in pipeline.adapter.frames():
                pipeline._process_frame(frame, meta)
                frames += 1
                if frames >= 40:
                    break
        finally:
            pipeline.adapter.stop()
            pipeline.adapter.join()
        records = pipeline.chain_store.get_all_records()
        anpr_records = []
        for record in records:
            payload = record.get("package", record) if isinstance(record, dict) else {}
            if payload.get("event_type") == "ANPR_READ" or payload.get("normalized_plate_text"):
                anpr_records.append({
                    key: payload.get(key)
                    for key in ("event_id", "camera_id", "stream_id", "track_id", "raw_plate_text", "normalized_plate_text", "plate_confidence", "ocr_confidence", "observations_count", "validation_status")
                })
        print(json.dumps({"frames": frames, "evidence_records": len(records), "anpr_records": anpr_records, "metrics": pipeline.metrics.summary()}, default=str))


if __name__ == "__main__":
    main()
