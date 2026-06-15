FROM python:3.11-slim

WORKDIR /app
COPY function.py .

# register/L1-bound FP 루프 (sqrt/sin/cos). 인자 = 반복 횟수(solo time knob) + rounds.
# 15e6 iters ≈ 수 초 compute (startup 오버헤드에 안 묻히게). graph-bfs(메모리 바운드) 대체 — CPU victim.
CMD ["python", "function.py", "15000000", "1"]
