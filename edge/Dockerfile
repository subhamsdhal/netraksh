# Builder-only dependencies include PyTorch/Ultralytics to export the bundled
# YOLO checkpoint exactly once. Nothing from this Python environment is copied
# into the free-tier runtime image.
FROM python:3.12-slim AS model-builder
WORKDIR /build
COPY edge/requirements.txt /build/requirements-build.txt
RUN pip install --no-cache-dir -r requirements-build.txt
COPY yolov8n.pt /build/yolov8n.pt
RUN python -c "from ultralytics import YOLO; YOLO('/build/yolov8n.pt').export(format='onnx', imgsz=640, opset=12, simplify=False, dynamic=True, device='cpu')" \
    && test -s /build/yolov8n.onnx

FROM python:3.12-slim AS runtime
WORKDIR /app
RUN groupadd -r netraksh && useradd -r -g netraksh -d /tmp/netraksh-edge -s /usr/sbin/nologin netraksh \
    && apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY edge/requirements-cloud.txt /app/requirements-cloud.txt
RUN pip install --no-cache-dir -r requirements-cloud.txt \
    && python -c "import cv2; assert hasattr(cv2, 'face') and hasattr(cv2.face, 'LBPHFaceRecognizer_create')" \
    && ! python -c "import torch" \
    && ! python -c "import easyocr" \
    && ! python -c "import ultralytics"

COPY edge/ /app/edge/
COPY shared/ /app/shared/
COPY demo/scripts/zones_config.json /app/demo/scripts/zones_config.json
COPY demo/videos/uploaded_demo.mp4 /app/demo/videos/uploaded_demo.mp4
COPY lpd_yunet.onnx face_recognition_sface_2021dec.onnx /app/
COPY --from=model-builder /build/yolov8n.onnx /app/yolov8n.onnx

RUN mkdir -p /tmp/netraksh-edge/keys /tmp/netraksh-edge/sources /tmp/netraksh-edge/.cache \
    && chown -R netraksh:netraksh /app /tmp/netraksh-edge

USER netraksh
ENV PYTHONPATH=/app \
    ENV=production \
    HOME=/tmp/netraksh-edge \
    XDG_CACHE_HOME=/tmp/netraksh-edge/.cache \
    EDGE_RUNTIME_DIR=/tmp/netraksh-edge \
    EDGE_SOURCE_CACHE_DIR=/tmp/netraksh-edge/sources \
    EDGE_KEY_DIR=/tmp/netraksh-edge/keys \
    EDGE_CONSTRAINED_CLOUD=true \
    ANPR_OCR_BACKEND=disabled \
    DETECTOR_RUNTIME=onnx_cpu \
    DETECTOR_MODEL_ONNX=/app/yolov8n.onnx

CMD ["python", "-m", "edge.cloud_worker"]
