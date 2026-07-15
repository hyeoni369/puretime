FROM python:3.11-slim

WORKDIR /app
COPY function.py .

# float_operation의 멀티워커 변형 (R-04 ablation): WORKERS=2 프로세스가 N을 반씩 나눠
# 같은 코어(컨테이너 cpuset)에서 실행 → sibling 간 self-wait 발생. N=6e6 → solo ~1.2s.
ENV WORKERS=2
CMD ["python", "function.py", "6000000", "1"]
