# PureTime 실험 설계 (최종 확정)

> SoCC 2026 2라운드 제출용. 5개 실험으로 P0 claim(C1·C3·C5·C6·C7) 전부 검증.
> 공통 testbed: **cgroup v2 격리 컨테이너로 서버리스 함수 실행 환경 재현**(Knative 미배포 — 측정에 필요한 건 cgroup 격리이며 모든 컨테이너 기반 서버리스의 공통 기반). core 0 제외 + victim/stressor 코어 핀 고정. victim 단일 스레드. NIC offload off.
> 모든 노이즈 환경의 G.T. = *조용한 노드의 solo run 분포*(점이 아니라 분포; 판정은 분포 겹침/2-표본 검정).
> 용어: PureTime이 산출하는 값은 **순수 실행 시간(noise-free makespan)**.

---

## 실험 1. PureTime 정확도 측정

### 실험 방법

- 각 리소스(CPU, Network, Block)에 dependent한 함수 3개를 FunctionBench에서 골라 사용
  - CPU = `float`, **Block I/O = `compression`** (이전 계획의 `dd`에서 변경), Network = cloud storage **업로드**(PureTime은 송신 TX만 추적하므로 업로드 경로 사용)
    - **block victim을 `dd`가 아니라 `compression`으로 하는 이유 (실측 확인)**: PureTime은 *스케줄러 큐 경합*을 제거하지 *장치 물리 dilation*(seek 등)은 못 뺀다(범위 밖). 순수 `dd`는 **block-only라 디스크를 포화**시켜 seek dilation이 지배 → 결과 깨짐(버퍼드 −70% 과다제거 / direct +45% 과소제거). **`compression`은 CPU+block 혼합**(파일 생성 write+fsync → 압축 read+write+fsync)이라 block 경합이 *"고갈"이 아니라 "wait-유발"* 강도에 머문다 → **보수적·안정적 ~63~68% removal**(과다제거 0). 실제 하니스(`exp_accuracy_by_type.sh`)도 `compression` 사용. (`dd`를 굳이 쓰려면 queue_depth=1 + O_DIRECT + 순차로 특수 튜닝해야 ~65~69% 비슷하게 나오지만 불안정 — 비권장.)
  - 각 함수는 **고정 입력**으로 실행하고, **solo run(동일 입력, 무부하)을 G.T.**로 삼음
- 리소스에 맞는 stress 도구로 부하를 주면서 함수를 실행하고, 함수의 solo run 실행 시간과 PureTime으로 추출한 순수 실행 시간의 차이를 비교
  - stress 도구의 부하 정도를 다르게 하여, 부하 수준에 따라 정확도가 어떻게 되는지 확인
  - **stressor(별도 cgroup)**: CPU = register/L1-bound 루프(cpuburn) · Block = fsync 쓰기(BFQ) · **Network = `iperf3 -c` (TCP, 별도 level≥2 cgroup), 강도 = `-P` 병렬 flow 수.** HTB 10mbit throttle 하에서 같은 TX qdisc 경합. (`exp_accuracy_by_type.sh` `NET_STRESS_FLOWS`; 이전 "업로더 컨테이너 N개"에서 교체 — victim은 uploader 1개 그대로.) iperf3 서버 필요, **TCP만**(UDP 미추적).
  - **실측 결과(wall ≥1.5× 의미있는 경합)**: CPU 99%@1.7× · Network 88~93%@4~5× = **≥80% removal 안정적**. **Block은 ~65~76%**(스케줄러 큐 경합만 제거; 장치 dilation은 범위 밖 — `block_rq_issue`가 dispatch 시점이라 [issue→complete] 대기 사각, ~16개 설정 실측 확정. claims-contract "최종 프레이밍 결정" 노트 참조). → 논문은 CPU·Net 강조, Block 정직 프레이밍.

### Figure

- "함수 별 E2E 실행시간 with stress", "E2E 실행 시간 without stress(G.T.)", "순수 실행 시간 with stress" 비교
- Stress 부하 강도에 따른 "함수 별 E2E 실행시간 with stress", "E2E 실행 시간 without stress(G.T.)", "순수 실행 시간 with stress"

---

## 실험 2. Mixed-noise 환경에서 PureTime의 성능 분석 with interval-merge

### 실험 방법

- 여러 리소스를 동시에 사용하는 FunctionBench의 video_processing(영상 download → OpenCV 흑백 변환 → 영상 upload) 함수 사용
  - 단일 스레드 고정, 다운로드·업로드 동기(blocking)
- Stress 도구를 이용하여 부하를 주면서 순수 실행 시간의 정확성 분석
  - Stress 도구들의 조합(CPU, Net, Block, CPU+Net, Net+Block, CPU+Block, CPU+Net+Block) 중 가장 순수 실행 시간의 정확성이 높게 나오는 상황 선택
  - 영상 크기 조절해가면서 리소스들의 interval 간에 겹치는 비율 조정하면서 다양하게 test

### Figure

- 리소스 간에 서로 얼마나 겹치는지에 따른 순수 실행 시간 성능을 with / without interval-merge 관점에서 분석
  - mixed noise에서 순수 실행 시간이 solo와 맞는 것 = 정확성 + merge 기여를 동시에 보임

---

## 실험 3. Input-variance한 함수에서 PureTime이 얼마나 잘 작동하는가?

### 실험 방법

- input에 따라 연산량이 달라지는 함수(`float`(sqrt/sin/cos 루프), face detect+sentiment 파이프라인)를 기반으로 테스트 진행
  - 두 번째 함수의 경우, **얼굴 수 0·1·5·10·15·30개**의 이미지로 테스트
- CPU stress 부하 주면서 함수 실행하고, 순수 실행 시간이 얼마나 정확한지 확인
  - stressor는 register/L1-bound로 유지(메모리 대역폭 미경합 → on-CPU IPC dilation 누수 차단; dilation은 PureTime 범위 밖)

### Figure

- input에 따른 "solo run", "순수 실행 시간 with stress", "E2E time with stress" 그래프

---

## 실험 4. baseline 방법론들과의 비교: 기존의 통계적인 접근방법과 비교

### 실험 방법

- 이전 실험들에서 얻은 데이터를 활용하며, 추가로 실험은 돌리지 않음
- input이 랜덤하게 들어간다는 전제하에, 함수의 실행시간 추이를 기존 통계적 방법론과 PureTime이 각각 어떻게 따라가는지 보여줘야 함
  - 각 호출의 **solo(해당 입력, 무부하)를 G.T. 기준선**으로 삼음(input이 호출마다 다르므로 시점마다 G.T.가 다름)
  - 실험 3에서 얼굴 수 0·1·5·10·15·30 + `float`(sqrt/sin/cos 루프) 함수에 넣은 값들을 랜덤하게 해서 사용
    - 각 입력 별로 몇 초 걸리는지 이미 알고있으므로, 입력들을 전부 셔플해서 그 순서로 들어간다고 가정 → 순서대로 몇 초 걸렸는지 구할 수 있음

### Figure

- G.T.(solo run), E2E time with stress, 순수 실행 시간 with stress의 흐름을 보여줌
  - 각 흐름에서 AWS Lambda, Azure Functions와 같은 상용 시스템에서 사용하는 통계적 방법이 어떻게 작동하는지 보여줘야 함
    - mean, P90 밴드를 그리고, 기존 방식은 제대로 작동하지 못하는 경우들을 나열하여 이를 보여줌
      - 노이즈 낀 wall은 밴드 초과(false alarm), 순수 실행 시간은 밴드 안(정상). 순수 실행 시간 분산↓로 밴드 좁아 진짜 회귀 더 빨리. (AWS CloudWatch Anomaly Detection 기본 mean±2σ 밴드)
      - KPA containerConcurrency 100 × util 70% = 70/pod 초과 시 scale-out. Little's Law로 노이즈 부푼 TimePerRequest→concurrency 70 넘김(over-provision), 순수 실행 시간은 미만. 가짜 pod = ⌈부푼/70⌉−⌈진짜/70⌉.
  - 결정 대조는 측정값 + 실제 기본 임계값(2σ, 70)으로 *서술*(counterfactual; 폐루프 미구동, future work)

---

## 실험 5. 오버헤드 분석: PureTime 켜면 함수의 실행 시간이 얼마나 증가하는지 + 시스템 전체의 리소스 사용량은 얼마나 증가하는지 확인

### 실험 방법

- 실험 1에서 사용한 함수들을 그대로 이용
- stress 부하 없는 환경에서 함수 solo run 실행 시간을 측정(여러 번 반복해 분포로 비교)
  - with and without PureTime
- PureTime 프로세스가 사용하는 CPU%, Memory 사용량 체크
- 오버헤드는 **online(eBPF hook + Loader 캡처)만** 고려. Analyzer는 offline에 수행되는 task로 critical path에 존재하지 않으므로 리소스 사용량/지연에서 제외(본문 명시)
- **Ring buffer 크기 주의**: 기본값은 고부하/경합 실험에서 드롭을 막으려고 **512MB**로 둔다(RSS ~1GB). 하지만 **이 오버헤드 측정에서는 RSS가 곧 측정 대상**이므로, `src/puretime.bpf.c`의 `events` 맵 `max_entries`를 **32MB로 내려서 빌드**한 뒤 측정한다(RSS ~70MB). 본문에는 측정에 쓴 크기를 명시. (드롭 발생 시 trailer의 `dropped_events>0` → 해당 run 무효, 크기 상향 후 재실행.)

### Figure

- 함수별 실행시간이 PureTime을 켜고 끄는 것에 따라 어떻게 변하는지 box plot
- 리소스 사용량은 본문에만 넣거나, Table으로 넣기

---

## 해석 원칙 (각주)

- **prune 자유, 전멸은 경고**: 결과가 잘 나온 victim·강도·조합만 본문에 쓰는 것은 자유. 단 C1(정확도)은 P0이므로, 어떤 victim·강도에서도 정확도가 안 나오면 "안 쓰면 그만"이 아니라 **설계 재검토 신호**다.
- **실험 2 문구**: "가장 정확성 높은 상황 선택"은 설계 노트 표현. 논문 본문 옮길 때는 cherry-pick 의심을 피하려 "겹침이 발생하는 조합에서 merge 유무 비교"로 표현.
- **데이터 재사용 관계**: 실험 2 ⊃ 실험 1(단일 노이즈) · 실험 4 = 실험 3 데이터 셔플 · (merge ablation) = 실험 2 데이터.
