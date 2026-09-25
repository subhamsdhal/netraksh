# Phase 6: Model Benchmark Criteria

## 1. Requirement
All hardware/runtime measurements must be executed on verified physical target devices.
If actual hardware is unavailable, results must be logged as `NOT MEASURABLE`. No synthetic latency generation is permitted.

## 2. Performance Segregation
Do not mix network latency into the model execution boundary.
Measure explicitly:
- `load_time_ms`
- `preprocessing_ms`
- `inference_ms`
- `postprocessing_ms`
- `total_e2e_ms`

## 3. Benchmark Record Schema
Each benchmark must define:
- `model`, `model_version`
- `weights_hash`
- `runtime`
- `hardware_profile`
- `input_resolution`, `precision` (FP32/FP16/INT8)
- `latency_ms`
- `memory_mb`
- `throughput`
- `dataset`, `dataset_version`
- `accuracy_metric`
- `condition_slice`
- `failure_count`
