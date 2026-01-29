FROM python:3.11-slim

WORKDIR /app

# Install boto3 for S3/MinIO compatibility
RUN pip install --no-cache-dir boto3

COPY function.py .

# Environment defaults (can be overridden at runtime)
ENV INPUT_FILE=/data/tmp.bin
ENV MINIO_ENDPOINT=http://165.194.27.225:9000
ENV MINIO_ACCESS_KEY=minioadmin
ENV MINIO_SECRET_KEY=minioadmin
ENV MINIO_BUCKET=uploads
ENV ITERATIONS=1

CMD ["python", "function.py"]
