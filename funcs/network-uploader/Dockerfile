FROM python:3.11-slim

WORKDIR /app

# Install boto3 for S3/MinIO compatibility
RUN pip install --no-cache-dir boto3

COPY function.py .

# Environment defaults (can be overridden at runtime)

# video: HPX source code, 6.7 MB
ENV DOWNLOAD_URL=https://github.com/STEllAR-GROUP/hpx/archive/refs/tags/1.4.0.zip
# resnet model from pytorch. 98M
ENV DOWNLOAD_URL=https://download.pytorch.org/models/resnet50-19c8e357.pth

ENV MINIO_ENDPOINT=http://165.194.27.225:9000
ENV MINIO_ACCESS_KEY=minioadmin
ENV MINIO_SECRET_KEY=minioadmin
ENV MINIO_BUCKET=uploads
ENV ITERATIONS=5

CMD ["python", "function.py"]
