FROM python:3.11-slim

RUN apt-get update && apt-get install -y iperf3 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY function.py .

ENV TARGET_HOST=165.194.27.225
ENV SIZE=100M

CMD ["python", "function.py"]
