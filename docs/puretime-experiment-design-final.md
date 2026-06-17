# PureTime 실험 설계 (최종 확정)

> SoCC 2026 2라운드 제출용. 5개 실험으로 P0 claim(C1·C3·C5·C6·C7) 전부 검증.
> 공통 testbed: **cgroup v2 격리 컨테이너로 서버리스 함수 실행 환경 재현**(Knative 미배포 — 측정에 필요한 건 cgroup 격리이며 모든 컨테이너 기반 서버리스의 공통 기반). core 0 제외 + victim/stressor 코어 핀 고정. victim 단일 스레드(**예외: 실험 2 interval-merge만 동시 2-스레드 + 스레드별 코어 핀** — 겹치는 wait을 만들려면 진짜 동시성 필요; CPU-경합 스레드는 그래도 단일 코어 핀이라 모델 가정 유지. 실험 2 "설계 변경" 참조). NIC offload off.
> 모든 노이즈 환경의 G.T. = *조용한 노드의 solo run 분포*(점이 아니라 분포; 판정은 분포 겹침/2-표본 검정).
> 용어: PureTime이 산출하는 값은 **순수 실행 시간(noise-free makespan)**.

---

## 실험 1. PureTime 정확도 측정

### 실험 방법

- 각 리소스(CPU, Network, Block)에 dependent한 함수 3개를 FunctionBench에서 골라 사용
  - CPU = `float`, **Block I/O = `compression`** (이전 계획의 `dd`에서 변경), Network = cloud storage **업로드**(PureTime은 송신 TX만 추적하므로 업로드 경로 사용)
    - **block victim 진화: `compression`(DEFLATE) → `compression` store 모드(archiving, I/O-bound)** [2026-06-16]: PureTime은 *스케줄러 큐 경합*을 제거하지 *장치 물리 dilation*(seek 등)은 못 뺀다(범위 밖). 원래는 순수 `dd`가 **디스크를 포화**시켜 seek dilation이 지배(결과 깨짐) → 이를 피하려 `compression`(DEFLATE, CPU+block 혼합)을 썼으나, CPU 부분이 안 부풀어 inflation이 2.5×·removal 87%에 묶였다. **`queue_depth=2` 전제조건(아래 ★)이 경합을 큐잉 층으로 직렬화해 포화/seek dilation을 막으므로, 이제 I/O-bound victim이 안전**하다 → victim을 **store 모드**(`COMPRESS_METHOD=stored` = zip 무압축 = read+write+fsync archiving, CPU 최소)로 바꿔 **inflation 3.2× · removal 92%**(둘 다 ↑). 하니스(`exp_accuracy_by_type.sh`)는 `compression` 이미지를 store 모드로 빌드.
      - **★ 측정 전제조건 ① `queue_depth=2` (2026-06-16 K=30 실측):** 기본 NCQ `queue_depth=32`에선 경합이 issue→complete(장치 내부)에 숨어 **removal 39%만** 나온다. `echo 2 > /sys/block/sdb/device/queue_depth`로 직렬화하면 경합이 [insert→issue]로 노출되어 잡힌다. depth-sweep(DEFLATE victim) 1→2→4→8→32 = 114%(과다제거)→83%→74→75→39%; depth=2가 sweet spot(depth=1은 과다직렬화로 과다제거). **store-모드 victim + depth=2 (K=50 accuracy): removal median ~91% @ 3.2×, nf/solo 1.20(보수적)**. 한계: 과다제거(nf<solo) 꼬리 ~13%(std 8pp), queue_depth knob 의존성. 하니스가 `BLOCK_QUEUE_DEPTH`(기본 2)로 설정·복원. (NIC offload off와 동일 성격의 전제조건.)
      - **★ 측정 전제조건 ② 채워진(단편화) HDD (2026-06-17 발견):** queue_depth=2만큼 중요한 두 번째 전제. **빈/깨끗한 디스크**에선 victim/fio I/O가 연속 fast track에 떨어져(solo ~2090ms) 경합이 [insert→issue] 큐에 안 쌓여 removal이 **45%로 붕괴**한다(queue_depth=2여도). **채워진/단편화 디스크**(실제 서버리스 노드처럼 — 타 테넌트 데이터)는 I/O가 느려(solo ~2940ms) 경합이 큐잉되어 잡힌다 → **91%**. 두 레짐 모두 내부 std 7~8로 안정(빈 31~58%, 채움 72~117%) → 측정 노이즈 아닌 *디스크 상태*. **committed `accuracy_K50`(91%)은 채워진 디스크에서 측정한 valid·현실적 값 — block run 전 `/mnt/hdd` 대량 파일을 지우지 말 것**(디스크를 비우면 45%). 명시적 per-run fio pre-fill은 HDD에서 너무 느려(120GB random-write ≫ 1h) 비실용적이므로, 디스크를 채워진 상태로 *유지*하는 게 답. **이 디스크-상태 의존성 때문에 fig 1b robustness sweep에서 Block은 제외**(여러 강도를 동일 디스크 상태로 재기 어려움) → 1b는 CPU+Network만, Block은 1a 대표값(91%)만.
  - 각 함수는 **고정 입력**으로 실행하고, **solo run(동일 입력, 무부하)을 G.T.**로 삼음
- 리소스에 맞는 stress 도구로 부하를 주면서 함수를 실행하고, 함수의 solo run 실행 시간과 PureTime으로 추출한 순수 실행 시간의 차이를 비교
  - stress 도구의 부하 정도를 다르게 하여, 부하 수준에 따라 정확도가 어떻게 되는지 확인
  - **stressor(별도 cgroup)**: CPU = register/L1-bound 루프(cpuburn) · Block = fsync 쓰기(BFQ) · **Network = `iperf3 -c` (TCP, 별도 level≥2 cgroup), 강도 = `-P` 병렬 flow 수.** HTB 10mbit throttle 하에서 같은 TX qdisc 경합. (`exp_accuracy_by_type.sh` `NET_STRESS_FLOWS`; 이전 "업로더 컨테이너 N개"에서 교체 — victim은 uploader 1개 그대로.) iperf3 서버 필요, **TCP만**(UDP 미추적).
  - **실측 결과(K=30/50, 2026-06-16)**: **CPU 98%@1.0→3.1×(강도 sweep) · Network 89%@4.8× · Block 92%@3.2×** = 셋 다 ≥89%. **Block은 `queue_depth=2` 전제조건 + store-모드 I/O-bound victim**(기본 depth=32에선 경합이 [issue→complete] 장치 내부에 숨어 39%만; depth=2로 직렬화하면 [insert→issue]로 노출되어 92%). 한계 정직 명시: block 과다제거 꼬리 ~13%(4/30, std 8pp)·queue_depth knob 의존성. claims-contract "Block 결론 수정 2026-06-16" 노트 참조. → 논문 CPU·Net·Block 모두 강하게 + block limitation 명시.

### Figure

- "함수 별 E2E 실행시간 with stress", "E2E 실행 시간 without stress(G.T.)", "순수 실행 시간 with stress" 비교
- Stress 부하 강도에 따른 "함수 별 E2E 실행시간 with stress", "E2E 실행 시간 without stress(G.T.)", "순수 실행 시간 with stress"

---

## 실험 2. Mixed-noise 환경에서 PureTime의 성능 분석 with interval-merge

### 실험 방법 (★ 2026-06-16 실측으로 원안에서 변경 — 아래 "설계 변경" 참조)

- victim = `funcs/video-processing`(numpy 흑백 변환 + boto3 MinIO 업로드), `--network=host`, cgroup v2 컨테이너.
  - **동시 2-스레드 + 스레드별 CPU affinity**(`os.sched_setaffinity`): `cpu_worker`(grayscale, register/L1-bound) → stressor가 포화시키는 경합 코어(CPU wait), `net_worker`(MinIO **sustained 대용량 업로드**, 1MB 객체) → **별도 빈 `IO_CORE`**(CPU 안 굶주려 TX 계속 발행 → throttle qdisc 큐잉이 net wait으로 포착). 두 워커가 다른 코어 → 한 cgroup에서 **CPU wait ∩ Net wait이 시간상 겹친다**.
  - `N_CPU`로 두 워커를 **동시 종료**하도록 balance(불균형이면 짧은 워커의 wait이 critical-path 밖 → 과다제거).
- stressor: CPU=`stress-ng --cpu-method float`(register/L1, 경합 코어 `--taskset`) · net=`iperf3 -P 4` + iface HTB 10mbit(victim TX가 같은 throttle qdisc에 큐잉, 실험 1의 89%-포착 regime 그대로).
- **CPU 경합 강도(stress-ng 워커 수) 1–4 sweep**으로 겹침 비율 8→30%를 만든다. 강도별 `N_CPU∝3/(강도+1)`로 balance 유지.

### ⚠️ 설계 변경: 원안 → 실측본 (이유)

원안(잠금 설계)은 **단일 스레드 + 동기 I/O victim**으로 **CPU·Net·Block 쌍/삼중 조합** 중 정확도 높은 걸 고르는 것이었으나, 실측에서 **그대로는 interval-merge가 보일 게 없음**이 드러나 다음 두 가지를 바꿨다(논문에 반영 필요):

1. **단일 스레드 → 동시 2-스레드(+스레드별 코어 핀).** 단일 스레드는 자원을 **직렬화**한다 — 선점 중(CPU wait)이면 I/O를 기다리는 게 아니고, throttle된 write에 막혀 있으면(D-state) runnable이 아니다 → CPU wait과 I/O wait이 **시간상 거의 분리** → 겹침≈0 → merge가 고칠 게 없다(실측: 단일스레드 겹침 ~9%, merged가 solo 위로). 겹침엔 **진짜 동시성**이 필요하며 이는 실제 파이프라인 서버리스(ExCamera NSDI'17, Sprocket SoCC'18: decode→process→encode→upload 동시)와 일치한다. 코어를 2개 쓰지만 **CPU-경합을 받는 `cpu_worker`는 여전히 단일 코어 핀**이라 PureTime의 single-core CPU-wait 모델 가정은 유지된다(`net_worker`는 CPU 경합을 안 만드는 자리일 뿐).
2. **조합에서 Block 제외 → CPU+Net.** Block은 `queue_depth=2`여도 무거운 경합에서 슬로다운이 `issue→complete` **device service time(PureTime 범위 밖, 미포착)**에 지배돼 merged가 solo **위로(under-removal)** 가고 naive가 오히려 solo에 가까워져 **스토리가 역전**된다(실측 확인). CPU(98%)·Net(89%)은 둘 다 잘 포착되는 자원이라 merged≈solo + naive≪solo의 정방향 스토리가 나온다. (Net이 잘 잡힌다는 건 별도 확인 — 초기 "net 범위 밖"은 bridge/NAT networking + CPU-stress 코어 핀으로 인한 오진이었고 `--network=host` + 코어 분리로 해결. TCP 백오프는 실험 1에서도 있던 ~11% 잔차일 뿐.)

### Figure (`fig7_interval_merge.pdf`, `plot_exp2_interval_merge.py`)

- 리소스 wait이 겹치는 비율에 따른 순수 실행 시간을 with / without interval-merge로 비교.
  - **Panel A**: x=측정 겹침비율(% of makespan), y=nf/solo. interval-merge는 solo=1 선에 평탄, naive는 우하향해 "impossible(nf<0)" 영역으로.
  - **Panel B**: 겹침 수준별 solo / merge / naive 막대.

### ★ 실측 결과 (2026-06-16, 완료 — `experiments/data/mixed_noise/`)

- 겹침 8→30% sweep: **interval-merge nf/solo 0.78–1.07(전 구간 valid, ≈solo)** vs **naive 0.79→−0.41**. 겹침↑면 naive는 발산해 **음수**(고겹침 강도3에서 7/10 runs 음수) — 혼자보다 빠를 수 없으니 물리적으로 불가능. = **mixed noise에서 merge는 solo를 복원(정확성), naive는 겹침을 이중차감(merge 기여)** 을 한 그림에 보인다. 겹침≈0(저강도)에선 merge≈naive → "겹침 없을 땐 무해" sanity check 자동 충족. 나머지 실험(1·3·4·5)도 완료.

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

- **(A) 지연 오버헤드 — ★ 2026-06-17 재설계 (아래 "설계 변경" 참조):** PureTime 지연 오버헤드는 추적하는 **커널 이벤트 수에 비례**한다. 따라서 victim 절대 실행시간을 비교하는 대신, **이벤트율(context-switch/s)을 x축으로 sweep**해 "이벤트율 vs 오버헤드" 곡선을 그린다. victim = `ctxsw-bench`(부모-자식 pipe 핑퐁: sched_switch를 결정적으로 생성, 같은 코어 협력 실행이라 CPU 경쟁 노이즈 없음; `COMPUTE_PER_ROUND`로 이벤트율 제어). 같은 워크로드를 with/without PureTime으로 K=15 측정(순서 counterbalance + CPU 터보 off + self-reported elapsed_ms).
- **(B) 자원 오버헤드:** PureTime 프로세스가 쓰는 CPU%·RSS 측정(절대 프로파일링).
- 오버헤드는 **online(eBPF hook + Loader 캡처)만** 고려. Analyzer는 offline에 수행되는 task로 critical path에 존재하지 않으므로 리소스 사용량/지연에서 제외(본문 명시)
- **Ring buffer 크기 주의**: 기본값은 고부하/경합 실험에서 드롭을 막으려고 **512MB**로 둔다(RSS ~1GB). 하지만 **이 오버헤드 측정에서는 RSS가 곧 측정 대상**이므로, `src/puretime.bpf.c`의 `events` 맵 `max_entries`를 **32MB로 내려서 빌드**한 뒤 측정한다(RSS ~70MB). 본문에는 측정에 쓴 크기를 명시. (드롭 발생 시 trailer의 `dropped_events>0` → 해당 run 무효, 크기 상향 후 재실행.)

### ⚠️ 설계 변경: w/vs w/o box plot → 이벤트율 vs 오버헤드 곡선 (이유)

원안은 "실험 1 함수들을 조용한 환경에서 with/without PureTime 실행시간 분포 비교(box plot)"였으나, 실측에서 **음수 오버헤드 문제**가 드러나 (A)지연 방식을 바꿨다(HPDC "PureTime 켜면 더 빠름" 논란과 동일):

- PureTime 지연 오버헤드는 **<1%로 측정 노이즈보다 작다**(트레이서가 별도 프로세스로 ring buffer를 drain, 커널 훅은 가벼움 → victim CPU를 거의 안 뺏음). 조용한 환경 w/vs w/o로는 절반이 음수(우연히 with가 빠름)로 나와 리뷰어가 의심한다.
- 부하를 줘 이벤트를 만들면 PureTime이 일하지만(측정 가능), victim을 부하와 **같은 코어에서 경쟁**시키면 CPU 몫 변동(±15~33%)이 ~1% 신호를 다시 묻는다(별도 코어=이벤트 없음=0).
- 해결: `ctxsw-bench`가 부모-자식 핑퐁으로 sched_switch를 **결정적·협력적으로** 생성 → CPU 쟁탈 없이 이벤트율만 제어. 이벤트율을 sweep하면 노이즈 없는 단조-양수 곡선.

### Figure (`fig3_overhead_time.pdf`, `plot_overhead_ctxsw.py`)

- **(A) fig3**: x=커널 이벤트율(×1000 context-switch/s), y=지연 오버헤드(%), 95% CI 에러바 + 선형 fit. **실측: 28K→717K switch/s에서 +2.2%→+44.4% 단조-선형, 전 구간 양수**(음수≈0) — "오버헤드는 이벤트율에 선형 비례, 현실적 함수율에서 낮음".
- **(B)**: PureTime 자체 자원(CPU~1%/RSS 71MB, events 맵 32MB) — 본문/Table 또는 fig4.

---

## 해석 원칙 (각주)

- **prune 자유, 전멸은 경고**: 결과가 잘 나온 victim·강도·조합만 본문에 쓰는 것은 자유. 단 C1(정확도)은 P0이므로, 어떤 victim·강도에서도 정확도가 안 나오면 "안 쓰면 그만"이 아니라 **설계 재검토 신호**다.
- **실험 2 문구**: 원안의 "조합 중 가장 정확한 상황 선택"은 cherry-pick 의심을 받으므로 **폐기**. 실측본은 **겹침 비율을 8→30%로 sweep**해 merge vs naive를 *연속 추세*로 보인다(cherry-pick 아님 — 모든 겹침 수준에서 merge가 valid, naive가 발산). 논문 표현도 "겹침 비율에 따른 merge 유무 비교"로.
- **데이터 재사용 관계**: 실험 4 = 실험 3 데이터 셔플 · (merge ablation 2-1) = 실험 2(1-3) 데이터. (원안의 "실험 2 ⊃ 실험 1 단일 노이즈 재사용"은 실측본에서 폐기 — 실험 2는 CPU+Net 동시 경합 전용 victim/sweep이라 단일-노이즈 데이터를 재사용하지 않는다.)
