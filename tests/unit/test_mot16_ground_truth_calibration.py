"""
NETRAKSH — Unit tests for scripts/collect_mot16_ground_truth_calibration.py's
pure logic: IoU computation and MOT16 gt.txt parsing. These are the two
pieces that decide whether a raw YOLO candidate gets labeled a real
detection (1), a real false positive (0), or excluded as genuinely
ambiguous — worth testing directly, independent of the real YOLO model or
a real MOT16 download, neither of which this test suite depends on.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from collect_mot16_ground_truth_calibration import (
    FP_IOU_THRESHOLD,
    GT_PEDESTRIAN_CLASS,
    MATCH_IOU_THRESHOLD,
    _iou,
    _load_ground_truth,
)


class TestIoU:
    def test_identical_boxes_iou_is_one(self):
        box = (10.0, 10.0, 50.0, 50.0)
        assert _iou(box, box) == 1.0

    def test_disjoint_boxes_iou_is_zero(self):
        a = (0.0, 0.0, 10.0, 10.0)
        b = (100.0, 100.0, 110.0, 110.0)
        assert _iou(a, b) == 0.0

    def test_known_real_overlap_fraction(self):
        # Two 10x10 boxes overlapping in a 5x10 strip: intersection=50,
        # union = 100+100-50=150, IoU = 50/150 = 1/3.
        a = (0.0, 0.0, 10.0, 10.0)
        b = (5.0, 0.0, 15.0, 10.0)
        assert _iou(a, b) == pytest.approx(1.0 / 3.0)

    def test_symmetric(self):
        a = (0.0, 0.0, 10.0, 10.0)
        b = (5.0, 5.0, 15.0, 15.0)
        assert _iou(a, b) == pytest.approx(_iou(b, a))

    def test_zero_area_box_does_not_crash(self):
        a = (5.0, 5.0, 5.0, 5.0)  # degenerate, zero-area
        b = (0.0, 0.0, 10.0, 10.0)
        assert _iou(a, b) == 0.0


class TestLoadGroundTruth:
    def test_parses_real_mot16_format_and_filters_to_pedestrian_class(self, tmp_path):
        gt_path = tmp_path / "gt.txt"
        gt_path.write_text(
            # frame,id,bb_left,bb_top,bb_w,bb_h,conf,class,visibility
            "1,1,10,20,30,40,1,1,1.0\n"   # real pedestrian -> kept
            "1,2,50,60,10,10,1,7,1.0\n"   # static person (class 7) -> excluded
            "1,3,70,80,10,10,0,1,1.0\n"   # conf=0 ("ignore") -> excluded
            "2,1,15,25,30,40,1,1,0.9\n"   # frame 2, real pedestrian -> kept
        )
        by_frame = _load_ground_truth(gt_path)
        assert len(by_frame[1]) == 1
        assert by_frame[1][0] == (10.0, 20.0, 40.0, 60.0)  # (x1,y1,x1+w,y1+h)
        assert len(by_frame[2]) == 1
        assert 3 not in by_frame or len(by_frame.get(3, [])) == 0

    def test_empty_file_gives_empty_dict(self, tmp_path):
        gt_path = tmp_path / "gt.txt"
        gt_path.write_text("")
        assert _load_ground_truth(gt_path) == {}


class TestLabelingThresholdsAreDisjoint:
    """Sanity: the match/FP thresholds used to decide 1 vs 0 vs 'excluded'
    (scripts/collect_mot16_ground_truth_calibration.py's main loop) must
    never overlap, or a single IoU value could be eligible for both labels."""

    def test_fp_threshold_below_match_threshold(self):
        assert FP_IOU_THRESHOLD < MATCH_IOU_THRESHOLD

    def test_pedestrian_class_is_the_documented_mot16_devkit_code(self):
        assert GT_PEDESTRIAN_CLASS == 1
