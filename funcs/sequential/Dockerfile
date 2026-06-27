FROM python:3.11-slim

WORKDIR /app
COPY function.py .

# ServerlessBench sequential ALU (register/L1 CPU). 인자 = times (solo time knob, 시간 ∝ times).
CMD ["python", "function.py", "10000000"]
