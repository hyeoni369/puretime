# PureTime Evaluation Experiment Guide

## 실험 개요

이 가이드는 PureTime 시스템의 성능 평가를 위한 실험 방법론을 설명합니다. 4일 내에 완료 가능하도록 우선순위에 따라 구성되어 있습니다.

### 핵심 메트릭: Noise Removal Efficiency

모든 정확도 실험은 다음 공식을 사용합니다:

```
Ground Truth Noise = T_contention - T_isolated
Removed Noise      = T_contention - T_puretime
Noise Removal Efficiency = (Removed Noise / Ground Truth Noise) × 100%
```

예시:
- T_contention = 18s (노이즈 환경에서 측정한 E2E 시간)
- T_isolated = 2s (격리 환경에서 측정한 E2E 시간)
- T_puretime = 2.6s (PureTime이 계산한 noise-free makespan)
- Ground Truth Noise = 18 - 2 = 16s
- Removed Noise = 18 - 2.6 = 15.4s
- **Efficiency = 15.4 / 16 × 100 = 96.25%**

---

## 실험 구조 및 일정

| 실험 | 우선순위 | 소요 시간 | 스크립트 |
|------|----------|-----------|----------|
| 노이즈 유형별 정확도 분석 | 필수 | 0.5일 | `exp_accuracy_by_type.sh` |
| 노이즈 강도별 정확도 분석 | 필수 | 0.5일 | `exp_accuracy_by_intensity.sh` |
| 시스템 오버헤드 측정 | 필수 | 0.5일 | `exp_overhead.sh` |
| Case Study: Canary 배포 | 권장 | 0.5일 | `exp_canary.sh` |
| Case Study: KPA 시뮬레이션 | 권장 | 1일 | `exp_kpa_simulation.sh` |

---

## 1. 노이즈 유형별 정확도 분석

### 목적
CPU, Network, Block I/O 세 가지 노이즈 유형에 대해 PureTime의 노이즈 제거 정확도를 비교합니다. 노이즈 강도는 고정하고 유형별 차이만 분석합니다.

### 스크립트 설정
`exp_accuracy_by_type.sh`의 상단 변수를 수정합니다:

```bash
# 노이즈 강도 (모든 유형에 동일하게 적용)
CONTENTION_CONTAINERS=4

# 반복 실험 횟수
ITERATIONS=10
```

### 워크로드
| 노이즈 유형 | Docker Image | 주요 대기 원인 |
|-------------|--------------|----------------|
| CPU | graph-bfs | WAIT_CPU (run queue) |
| Network | network-uploader | WAIT_NET (qdisc queue) |
| Block I/O | compression | WAIT_BIO (I/O scheduler) |

### 실행
```bash
sudo ./exp_accuracy_by_type.sh /results/accuracy_by_type
```

### 결과 분석 및 시각화
```bash
python3 analysis/compute_metrics.py /results/accuracy_by_type/results.csv \
    --output /results/accuracy_by_type/metrics.json \
    --latex /results/accuracy_by_type/table.tex

python3 analysis/plot_results.py by_type /results/accuracy_by_type/results.csv \
    --output /results/accuracy_by_type/
```

### 예상 결과
Grouped Bar Chart로 각 노이즈 유형별 T_isolated, T_contention, T_puretime을 비교하고, 각 유형별 Noise Removal Efficiency(%)를 표시합니다.

---

## 2. 노이즈 강도별 정확도 분석

### 목적
동시 실행 컨테이너 수(노이즈 강도)가 증가함에 따라 PureTime의 정확도가 어떻게 변화하는지 분석합니다. 노이즈 유형은 CPU로 고정합니다.

### 스크립트 설정
`exp_accuracy_by_intensity.sh`의 상단 배열 변수를 수정합니다:

```bash
# 노이즈 강도별 컨테이너 수 배열
CONTAINER_COUNTS=(1 2 4 8 16)

# 반복 실험 횟수
ITERATIONS=10
```

### 실행
```bash
sudo ./exp_accuracy_by_intensity.sh /results/accuracy_by_intensity
```

### 결과 분석 및 시각화
```bash
python3 analysis/compute_metrics_intensity.py /results/accuracy_by_intensity/results.csv

python3 analysis/plot_results.py by_intensity /results/accuracy_by_intensity/results.csv \
    --output /results/accuracy_by_intensity/
```

### 예상 결과
컨테이너 수가 증가할수록 T_contention은 증가하지만, T_puretime은 T_isolated에 근접하게 유지되어 높은 Efficiency를 보여줍니다.

---

## 3. 시스템 오버헤드 측정

### 목적
PureTime eBPF 프로그램이 시스템에 미치는 오버헤드를 측정합니다.

### 측정 항목
1. **실행 시간 지연**: PureTime on/off 상태에서 동일 워크로드 실행 시간 비교
2. **자원 소비량**: CPU 사용률, 메모리 사용량

### 스크립트 설정
`exp_overhead.sh`의 상단 변수를 수정합니다:

```bash
# 측정 반복 횟수
ITERATIONS=20

# 워크로드 유형
WORKLOADS=("graph-bfs" "network-uploader" "compression")
```

### 예상 결과
PureTime의 eBPF 프로그램은 커널 레벨에서 동작하므로 오버헤드가 매우 낮을 것으로 예상됩니다 (< 1% latency overhead).

---

## 4. Case Study: Canary 배포에서 False Alarm 감지

### 목적
Canary 배포 시나리오에서 noisy neighbor로 인한 false positive alarm을 PureTime이 어떻게 방지하는지 보여줍니다.

### 시나리오
1. 기존 버전(v1)과 새 버전(v2)을 동시 배포
2. Noisy neighbor로 인해 v2의 latency가 증가
3. 기존 모니터링: v2가 느리다고 판단 → **False Alarm** (실제로는 동일 성능)
4. PureTime: noise-free makespan으로 비교 → v1과 v2 성능 동일 확인

### 실행
```bash
sudo ./exp_canary.sh /results/canary
```

---

## 5. Case Study: KPA Autoscaling 시뮬레이션

### 목적
Knative Pod Autoscaler(KPA)의 Concurrency 기반 스케일링 결정이 noisy neighbor로 인해 어떻게 오판하는지, 그리고 PureTime이 이를 어떻게 방지하는지 시뮬레이션합니다.

### 배경: KPA의 동작 원리
KPA는 Little's Law를 기반으로 합니다:

```
Concurrency = RPS × Latency
```

따라서:
- Latency가 증가하면 → Concurrency 증가로 인식
- KPA가 "부하 증가"로 오인 → 불필요한 scale-out
- **Over-provisioning으로 인한 비용 낭비**

### PureTime의 해결책
PureTime이 noise-free latency를 제공하면:
- 실제 Concurrency를 정확히 계산
- 불필요한 scale-out 방지
- 비용 절감 효과

### 스크립트 설정
`exp_kpa_simulation.sh`의 상단 변수를 수정합니다:

```bash
# 테스트할 RPS 값들
TARGET_RPS_VALUES=(1 5 10 20)

# Noisy neighbor 컨테이너 수
NOISE_CONTAINER_COUNTS=(0 2 4 8)

# KPA target concurrency (Knative 기본값)
TARGET_CONCURRENCY=100
```

### 실행
```bash
sudo ./exp_kpa_simulation.sh /results/kpa_simulation
```

### 결과 분석 및 시각화
```bash
python3 analysis/plot_results.py kpa /results/kpa_simulation/kpa_analysis.json \
    --output /results/kpa_simulation/
```

### 예상 결과
1. **Concurrency 비교**: Observed Concurrency vs PureTime Concurrency
2. **Over-provisioning Rate**: Noise level별 불필요한 scale-out 비율
3. **Latency Inflation**: Noise로 인한 latency 부풀림 정도

---

## 테스트베드 환경

### 메인 서버
| 항목 | 사양 |
|------|------|
| CPU | AMD Ryzen 9 9900X |
| RAM | 96GB |
| Storage | 1TB NVMe + 2TB HDD |
| Network | 1Gbps |

### MinIO 서버 (Network 실험용)
| 항목 | 사양 |
|------|------|
| CPU | Intel Xeon E5-1620 |
| RAM | 64GB |
| Storage | 8TB HDD |
| Network | 1Gbps |
| Endpoint | http://165.194.27.225:9000 |

### 환경 설정
- **Block I/O**: HDD 사용 (`/mnt/hdd/tmp`), BFQ I/O scheduler
- **Network**: qdisc 대역폭 제한 (10Mbps), TSO/GSO/GRO 비활성화
- **CPU**: `--cpuset-cpus=0`으로 단일 코어에 컨테이너 배치

---

## 시각화 전략

### Grouped Bar Chart 사용 이유
1. **직관적 비교**: T_isolated, T_contention, T_puretime을 나란히 배치
2. **페이지 활용**: 큰 그래프로 페이지를 효과적으로 차지
3. **효과 강조**: PureTime의 노이즈 제거 효과가 시각적으로 명확

### 그래프 구성
| Figure | X축 | Y축 | 범례 |
|--------|-----|-----|------|
| 유형별 정확도 | Contention Type | Execution Time (ms) | T_isolated, T_contention, T_puretime |
| 강도별 정확도 | # Containers | Execution Time (ms) | T_isolated, T_contention, T_puretime |
| KPA Concurrency | RPS | Concurrency | Observed, PureTime |
| KPA Over-prov | Noise Containers | False Scale-out Rate (%) | RPS별 색상 |

---

## 체크리스트

### 실험 전
- [ ] Docker 이미지 빌드 완료
- [ ] MinIO 서버 접근 확인
- [ ] HDD 마운트 확인 (`/mnt/hdd/tmp`)
- [ ] PureTime 바이너리 빌드 확인
- [ ] root 권한 확인

### 실험 중
- [ ] 각 실험 전 시스템 idle 상태 확인
- [ ] trace 파일 생성 확인 (`/var/log/puretime/`)
- [ ] 컨테이너 정상 종료 확인

### 실험 후
- [ ] 결과 파일 백업
- [ ] 메트릭 계산 완료
- [ ] 시각화 생성 완료
- [ ] LaTeX 테이블 생성 완료

---

## 문제 해결

### cgroup ID 추출 실패
```bash
# Docker cgroup v2 확인
cat /proc/1/cgroup

# cgroup 경로 수동 확인
docker inspect --format '{{.State.Pid}}' <container_id>
cat /proc/<pid>/cgroup
```

### PureTime trace 파일 없음
```bash
# PureTime 로그 확인
journalctl -u puretime

# 수동 실행으로 디버깅
./src/puretime -t 10 -v
```

### Network throttle 실패
```bash
# tc 상태 확인
tc qdisc show dev <interface>

# 인터페이스 이름 확인
ip route get 165.194.27.225
```
