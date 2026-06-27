FROM python:3.11-slim

WORKDIR /app
COPY function.py .

# FaaSDom factors: trial-division (register/L1 CPU). 인자 = n (solo time knob, 시간 ∝ sqrt(n)).
CMD ["python", "function.py", "500000000000000"]
