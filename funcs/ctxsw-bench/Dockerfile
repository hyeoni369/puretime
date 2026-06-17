FROM python:3.11-slim

# Context-switch microbenchmark (실험 5 overhead): 부모-자식 pipe 핑퐁으로 sched_switch를
# 결정적으로 생성. 같은 코어 핀 + 협력적 번갈기라 CPU 경쟁 노이즈 없이 이벤트만 만든다.
WORKDIR /app
COPY function.py .

ENV ROUNDS=200000
ENV COMPUTE_PER_ROUND=0

CMD ["python3", "function.py"]
