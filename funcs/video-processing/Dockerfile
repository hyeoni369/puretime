FROM python:3.11-slim

# opencv (video read/write + grayscale) + boto3 (MinIO upload) + numpy.
# opencv-python-headless bundles the FFmpeg backend for VideoCapture/VideoWriter.
RUN pip install --no-cache-dir opencv-python-headless==4.10.0.84 numpy boto3

WORKDIR /app
COPY function.py .
RUN mkdir -p /tmp/video_test

ENV VIDEO_FRAMES=300
ENV FRAME_W=640
ENV FRAME_H=480
ENV WORK_DIR=/tmp/video_test
ENV MINIO_ENDPOINT=http://165.194.27.225:9000
ENV MINIO_ACCESS_KEY=minioadmincslab
ENV MINIO_SECRET_KEY=minioadmincslab
ENV MINIO_BUCKET=uploads
# single-thread numpy/BLAS (design: single-threaded victim)
ENV OMP_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1

CMD ["python3", "function.py"]
