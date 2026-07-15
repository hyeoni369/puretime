FROM python:3.11-slim

WORKDIR /app
COPY function.py .
RUN pip install --no-cache-dir pyaes

# aes의 멀티워커 변형 (R-04 ablation): WORKERS=2가 rounds를 반씩, 같은 코어에서.
ENV WORKERS=2
CMD ["python", "function.py", "16384", "40"]
