FROM python:3.11-slim

RUN pip install --no-cache-dir boto3

WORKDIR /app
COPY function.py .

# FunctionBench s3_download_upload: boto3 download(RX)+upload(TX). upload-TX가 측정 대상.
ENV MINIO_ENDPOINT=http://165.194.27.225:9000
ENV INPUT_BUCKET=uploads
ENV OUTPUT_BUCKET=uploads
ENV OBJECT_KEY=s3dlul_input.bin
CMD ["python", "function.py"]
