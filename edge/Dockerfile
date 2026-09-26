FROM python:3.12-slim

WORKDIR /app

# Add non-root user
RUN groupadd -r netraksh && useradd -r -g netraksh netraksh

# Install OS dependencies for OpenCV (libgl1, libglib2.0-0)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Edge dependencies
COPY edge/requirements.txt .
# Ultralytics and EasyOCR declare overlapping non-contrib OpenCV wheels.
# Reinstall contrib last so the selected LBPH pipeline retains cv2.face.
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --force-reinstall --no-deps \
       opencv-contrib-python-headless==4.10.0.84 \
    && python -c "import cv2; assert hasattr(cv2, 'face') and hasattr(cv2.face, 'LBPHFaceRecognizer_create')"

# Copy source code
COPY edge/ /app/edge/
COPY shared/ /app/shared/
COPY demo/scripts/zones_config.json /app/demo/scripts/zones_config.json
COPY demo/videos/uploaded_demo.mp4 /app/demo/videos/uploaded_demo.mp4
COPY yolov8n.pt lpd_yunet.onnx face_recognition_sface_2021dec.onnx /app/

# Export once at image-build time.  The running free-tier worker uses only
# ONNX Runtime + NumPy; PyTorch/Ultralytics are not imported by the ONNX path.
RUN python -c "from ultralytics import YOLO; YOLO('/app/yolov8n.pt').export(format='onnx', imgsz=640, opset=12, simplify=False, dynamic=True, device='cpu')" \
    && test -s /app/yolov8n.onnx

# Free Render web services have no persistent disk.  Runtime state is an
# explicitly disposable cache; durable uploads remain in Supabase Storage.
RUN mkdir -p /tmp/netraksh-edge/keys /tmp/netraksh-edge/sources \
    && chown -R netraksh:netraksh /app /tmp/netraksh-edge

# Run as non-root
USER netraksh

# Set correct pythonpath
ENV PYTHONPATH=/app
ENV ENV=production
ENV EDGE_RUNTIME_DIR=/tmp/netraksh-edge
ENV EDGE_SOURCE_CACHE_DIR=/tmp/netraksh-edge/sources
ENV EDGE_KEY_DIR=/tmp/netraksh-edge/keys
ENV DETECTOR_RUNTIME=onnx_cpu
ENV DETECTOR_MODEL_ONNX=/app/yolov8n.onnx

# Explicit production edge entrypoint
CMD ["python", "-m", "edge.cloud_worker"]
