FROM python:3.11-slim

WORKDIR /app
COPY function.py .
RUN mkdir -p /tmp/test

# FaaSDom filesystem: 다수 소파일 write+read (block I/O). WORK_DIR을 바인드마운트한 실디스크로.
ENV WORK_DIR=/tmp/test
# 인자 = n(파일 수) size(바이트). filled HDD + queue_depth=2 전제(exp_accuracy BLOCK_QUEUE_DEPTH).
CMD ["python", "function.py", "10000", "10240"]
