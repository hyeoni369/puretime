FROM python:3.11-slim

# Pipelined victim: numpy (per-chunk grayscale, CPU) + boto3 (per-chunk MinIO upload, Net-TX).
RUN pip install --no-cache-dir numpy boto3

WORKDIR /app
COPY function.py .
RUN mkdir -p /tmp/video_test

ENV VIDEO_FRAMES=150
ENV FRAME_W=640
ENV FRAME_H=480
ENV GRAYSCALE_PASSES=6
ENV WORK_DIR=/tmp/video_test
ENV MINIO_ENDPOINT=http://165.194.27.225:9000
ENV MINIO_ACCESS_KEY=minioadmincslab
ENV MINIO_SECRET_KEY=minioadmincslab
ENV MINIO_BUCKET=uploads
# single-thread numpy/BLAS (design: single-threaded victim)
ENV OMP_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1

CMD ["python3", "function.py"]
