FROM python:3.11-slim

WORKDIR /app
COPY function.py .

# Create work directory with proper permissions
RUN mkdir -p /tmp/compression_test

ENV NUM_FILES=5
ENV FILE_SIZE_MB=10
ENV ITERATIONS=1
ENV WORK_DIR=/tmp/compression_test

CMD ["python3", "function.py"]
