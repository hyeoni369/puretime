FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends iperf3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY function.py .

# FunctionBench iPerf3: forward(TX). 고정 바이트(-n)로 경합 시 makespan이 늘게(PureTime 측정용).
ENV IPERF_SERVER=165.194.27.225
ENV IPERF_PORT=5201
ENV IPERF_BYTES=5M
CMD ["python", "function.py"]
