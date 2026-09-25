#!/usr/bin/env python
"""
NETRAKSH — Interactive zone definition tool.

Click points on a real frame from your actual camera or video to define a
zone's polygon in the normalized 0-1 coordinates demo/scripts/zones_config.json
expects (see edge/rules/modules.py::normalize_point). This is how the
placeholder zones shipped in that file become genuinely correct ones for
your demo footage — by clicking real points, not by guessing coordinates.

Usage:
    python scripts/define_zone.py --source 0 --zone-id fence-perimeter-1 \\
        --zone-type fence --name "Perimeter Fence Line" --camera-id edge-001

    python scripts/define_zone.py --source demo/videos/clip.mp4 \\
        --zone-id trip-line-1 --zone-type boundary --name "Trip Line" \\
        --camera-id edge-001

--source accepts a webcam index (e.g. "0") or a video file path — same
convention as edge/main.py's VIDEO_SOURCE env var.

Controls in the window:
    Left click   — add a point
    u            — undo the last point
    Enter        — finish and save (fence/checkpoint/verification need >= 3
                   points; boundary/line needs exactly 2)
    Esc          — cancel without saving

Re-running with the same --zone-id replaces that zone in the config file;
every other zone already there is left untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

MIN_POINTS = {"fence": 3, "checkpoint": 3, "verification": 3, "boundary": 2}
EXACT_POINTS = {"boundary": 2}  # a line is exactly 2 points, not "at least 2"


def grab_one_frame(source: str):
    """Opens `source` (webcam index or file path) and returns a single frame."""
    import cv2

    cap = cv2.VideoCapture(int(source) if source.isdigit() else source)
    if not cap.isOpened():
        raise SystemExit(f"Could not open video source: {source}")
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit(f"Could not read a frame from: {source}")
    return frame


def points_to_normalized(points_px: List[Tuple[int, int]], frame_width: int, frame_height: int) -> List[dict]:
    """Pure, testable: pixel points -> the normalized {x, y} dicts the config file stores."""
    return [{"x": round(x / frame_width, 4), "y": round(y / frame_height, 4)} for x, y in points_px]


def upsert_zone(config: dict, new_zone: dict) -> dict:
    """
    Pure, testable: replaces any existing zone with the same zone_id, or
    appends if none exists — leaves every other zone in the config untouched.
    """
    config = dict(config)
    zones = list(config.get("zones", []))
    zones = [z for z in zones if z.get("zone_id") != new_zone["zone_id"]]
    zones.append(new_zone)
    config["zones"] = zones
    return config


def build_zone(
    zone_id: str, camera_id: str, name: str, zone_type: str,
    points_px: List[Tuple[int, int]], frame_width: int, frame_height: int,
) -> dict:
    return {
        "zone_id": zone_id,
        "camera_id": camera_id,
        "name": name,
        "zone_type": zone_type,
        "polygon": {"points": points_to_normalized(points_px, frame_width, frame_height)},
        "owning_command_id": "COMMAND_A",
    }


def _validate_point_count(zone_type: str, count: int) -> Optional[str]:
    """Returns an error message if `count` is invalid for `zone_type`, else None."""
    if zone_type in EXACT_POINTS and count != EXACT_POINTS[zone_type]:
        return f"A '{zone_type}' zone needs exactly {EXACT_POINTS[zone_type]} points — have {count}."
    if count < MIN_POINTS[zone_type]:
        return f"Need at least {MIN_POINTS[zone_type]} points for a '{zone_type}' zone — have {count}."
    return None


def run_click_loop(frame, zone_type: str) -> List[Tuple[int, int]]:
    """The interactive cv2 window. Returns the clicked points, or [] if cancelled."""
    import cv2

    points_px: List[Tuple[int, int]] = []

    def on_mouse(event, x, y, flags, userdata):
        if event == cv2.EVENT_LBUTTONDOWN:
            points_px.append((x, y))

    window = "NETRAKSH define_zone -- click points, Enter to save, u to undo, Esc to cancel"
    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)

    try:
        while True:
            display = frame.copy()
            for i, (x, y) in enumerate(points_px):
                cv2.circle(display, (x, y), 5, (0, 255, 0), -1)
                if i > 0:
                    cv2.line(display, points_px[i - 1], (x, y), (0, 255, 0), 2)
            if zone_type != "boundary" and len(points_px) >= 3:
                cv2.line(display, points_px[-1], points_px[0], (0, 255, 0), 1)
            cv2.putText(
                display, f"{len(points_px)} point(s) -- need {MIN_POINTS[zone_type]}"
                f"{'' if zone_type in EXACT_POINTS else '+'}",
                (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2,
            )
            cv2.imshow(window, display)

            key = cv2.waitKey(20) & 0xFF
            if key == 27:  # Esc
                return []
            if key == ord("u") and points_px:
                points_px.pop()
            if key == 13:  # Enter
                error = _validate_point_count(zone_type, len(points_px))
                if error:
                    print(error)
                    continue
                return points_px
    finally:
        cv2.destroyAllWindows()


def main() -> None:
    parser = argparse.ArgumentParser(description="Click real points on a frame to define a NETRAKSH zone")
    parser.add_argument("--source", required=True, help="Webcam index (e.g. 0) or video file path")
    parser.add_argument("--zone-id", required=True)
    parser.add_argument("--zone-type", required=True, choices=list(MIN_POINTS.keys()))
    parser.add_argument("--name", required=True)
    parser.add_argument("--camera-id", required=True)
    parser.add_argument("--config-path", default=os.path.join("demo", "scripts", "zones_config.json"))
    args = parser.parse_args()

    frame = grab_one_frame(args.source)
    frame_height, frame_width = frame.shape[:2]

    points_px = run_click_loop(frame, args.zone_type)
    if not points_px:
        print("Cancelled — nothing saved.")
        return

    new_zone = build_zone(args.zone_id, args.camera_id, args.name, args.zone_type, points_px, frame_width, frame_height)

    if os.path.exists(args.config_path):
        with open(args.config_path) as f:
            config = json.load(f)
    else:
        config = {"zones": []}
    config = upsert_zone(config, new_zone)

    with open(args.config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(
        f"Saved zone '{args.zone_id}' ({len(points_px)} points, frame {frame_width}x{frame_height}) "
        f"to {args.config_path}"
    )


if __name__ == "__main__":
    main()
