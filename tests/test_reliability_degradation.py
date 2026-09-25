import pytest
import numpy as np
from shared.constants import SceneCondition, CameraHealthState, HealthReason
from edge.health.camera_health import CameraHealthMonitor
from edge.condition.scene_condition import SceneConditionClassifier
from shared.schemas import CameraHealthReport, SceneConditionReport

def test_camera_health_graceful_degradation():
    monitor = CameraHealthMonitor(camera_id="test_cam")
    
    import time
    # 1. Normal frame
    normal_frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
    report = monitor.update(normal_frame, frame_timestamp=time.time())
    assert report.health_state == CameraHealthState.OK
    
    # 2. Frozen frames (Zero variance across time)
    # Feed the exact same frame multiple times to trigger frozen stream
    frozen_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
    for i in range(50):
        report = monitor.update(frozen_frame, frame_timestamp=time.time() + i * 0.1)
    
    assert report.health_state == CameraHealthState.FAILED
    assert report.health_reason == HealthReason.FROZEN_STREAM

    # 3. Corrupted / Blank frame (zero variance spatially)
    blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    report = monitor.update(blank_frame, frame_timestamp=time.time() + 10.0)
    # The monitor might need history to recover or will immediately flag spatial variance failure
    assert report.health_state in [CameraHealthState.FAILED, CameraHealthState.DEGRADED]

def test_scene_condition_graceful_degradation():
    classifier = SceneConditionClassifier(camera_id="test_cam")
    
    # 1. Normal frame (high variance so it passes contrast > 30)
    normal_frame = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
    report = classifier.classify(normal_frame)
    assert report.condition == SceneCondition.CLEAR_DAY
    
    # 2. Fog / Low Contrast (Uniform gray)
    fog_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
    noise = np.random.randint(-2, 3, (480, 640, 3)).astype(np.int16)
    fog_frame = np.clip(fog_frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    report = classifier.classify(fog_frame)
    assert report.condition == SceneCondition.FOG_RAIN
    
    # 3. Low Light Night (Very dark)
    dark_frame = np.random.randint(0, 20, (480, 640, 3), dtype=np.uint8)
    report = classifier.classify(dark_frame)
    assert report.condition == SceneCondition.LOW_LIGHT_NIGHT

    # 4. Glare (Extreme bright spot > 15% of frame)
    glare_frame = np.random.randint(50, 150, (480, 640, 3), dtype=np.uint8)
    glare_frame[100:400, 200:500] = 255 # Blown out highlight (300x300 = 90k pixels = ~29%)
    report = classifier.classify(glare_frame)
    assert report.condition == SceneCondition.GLARE
