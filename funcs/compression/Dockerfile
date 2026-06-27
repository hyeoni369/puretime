FROM python:3.11-slim

WORKDIR /app
COPY function.py .

# Create work directory with proper permissions
RUN apt-get update && apt-get install -y --no-install-recommends fio \
    && rm -rf /var/lib/apt/lists/* && mkdir -p /tmp/compression_test

ENV NUM_FILES=1
ENV FILE_SIZE_MB=100
ENV ITERATIONS=1
ENV WORK_DIR=/tmp/compression_test
# stored = 무압축(I/O-bound, CPU↓ → block inflation↑); deflate = CPU-heavy(원래). 파일럿용.
ENV COMPRESS_METHOD=stored

CMD ["python3", "function.py"]
