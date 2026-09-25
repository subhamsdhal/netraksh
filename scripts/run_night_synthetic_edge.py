"""Real EdgePipeline fallback acceptance on a synthetic non-sensitive scene."""
from pathlib import Path
import json
import sqlite3
import tempfile
import time
import sys
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from edge.main import EdgePipeline
from edge.evidence.packager import EdgeKeyManager
from edge.ingestion.camera_adapter import FrameMetadata
from shared.constants import StreamState


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="netraksh-night-edge-", ignore_cleanup_errors=True) as temp:
        p = Path(temp)
        cid = "night-synthetic-edge"
        config = {"camera_id": cid, "video_source": str(root / "demo/videos/vtest.avi"),
                  "zones_config_path": str(root / "demo/scripts/zones_config.json"),
                  "key_dir": str(p / "certs"), "chain_db_path": str(p / "chain.db"),
                  "sync_db_path": str(p / "sync.db"), "clip_dir": str(p / "clips"),
                  "backend_url": "http://127.0.0.1:59999"}
        key = EdgeKeyManager(private_key_path=str(p / "certs" / f"{cid}.key"),
                             public_key_path=str(p / "certs" / f"{cid}.pub"))
        key.load_or_generate(allow_generate=True)
        pipeline = EdgePipeline(config)
        pipeline.detector.load()
        # The fixture feeds frames directly rather than starting the adapter
        # reader thread; mark the stream connected so Gate 1 evaluates pixels
        # instead of treating the harness as a disconnected source.
        pipeline.adapter._set_state(StreamState.CONNECTED)
        frame_states = []
        for i in range(14):
            rng = np.random.RandomState(i)
            frame = rng.randint(0, 20, (480, 640, 3), dtype=np.uint8)
            x = 40 + i * 18
            cv2.rectangle(frame, (x, 190), (x + 90, 300), (150, 150, 150), -1)
            meta = FrameMetadata(i, time.time(), i / 10.0, 10.0, 640, 480, "synthetic")
            pipeline._process_frame(frame, meta)
            frame_states.append({"health": str(pipeline._last_health.health_state), "reason": str(pipeline._last_health.health_reason), "lighting": str(pipeline.condition_classifier.classify(frame).lighting_state), "gate_runs": pipeline.adaptive_gate.get_stats().get("frames_run")})
        records = pipeline.chain_store.get_all_records()
        queue_payloads = []
        with sqlite3.connect(str(p / "sync.db")) as conn:
            for (payload_json,) in conn.execute("SELECT payload_json FROM sync_queue ORDER BY sequence_number"):
                queue_payloads.append(json.loads(payload_json).get("evidence_package", {}))
        events = []
        record_summaries = []
        for record in records:
            payload = record.get("package", record) if isinstance(record, dict) else {}
            record_summaries.append({k: payload.get(k) for k in ("event_type", "scene_condition", "decision_state", "lighting_state", "detection_method", "motion_area", "motion_persistence")})
            if payload.get("event_type"):
                events.append({k: payload.get(k) for k in (
                    "event_type", "lighting_state", "mean_luminance", "detection_method",
                    "motion_area", "motion_persistence", "decision_state", "severity")})
        print(json.dumps({"frames": 14, "frame_states": frame_states, "evidence_records": len(records), "record_summaries": record_summaries, "queue_payloads": [{k: p.get(k) for k in ("event_type", "lighting_state", "detection_method", "motion_area", "motion_persistence", "decision_state", "severity")} for p in queue_payloads], "events": events,
                          "metrics": pipeline.metrics.summary()}, default=str))


if __name__ == "__main__":
    main()
