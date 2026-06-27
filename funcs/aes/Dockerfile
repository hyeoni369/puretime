FROM python:3.11-slim

RUN pip install --no-cache-dir pyaes

WORKDIR /app
COPY function.py .

# vSwarm aes: pyaes AES-CTR. 인자 = size(평문 바이트, L1) rounds(반복).
CMD ["python", "function.py", "16384", "40"]
