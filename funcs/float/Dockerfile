FROM python:3.11-slim

WORKDIR /app
COPY function.py .

# register/L1-bound FP 루프 (sqrt/sin/cos). 인자 = 반복 횟수(solo time knob) + rounds.
# 5e6 iters ≈ 수 초 (정확도 실험1의 고정 입력). graph-bfs(메모리 바운드) 대체 — CPU victim/stressor.
CMD ["python", "function.py", "5000000", "1"]
