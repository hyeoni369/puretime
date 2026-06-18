# PureTime §5 Evaluation — Figure 최종 스펙

> SoCC 2026 2라운드. 실험 1~5에 대응하는 figure 6개 + table 1개.
> 이 문서는 figure를 *그릴 수 있는 수준*의 최종 명세. 색·정규화·형태가 §3 figure와 일관.
> 상태(2026-06-17 갱신): 실제 구현·커밋된 결과에 맞춰 정정 — Figure 5(오버헤드) 합격기준 완화(중앙값<1.5%, 개별 음수 허용)+이벤트율 곡선 보조, Figure 2(실험2) victim을 동시 2-스레드 CPU+Net으로, Block 91~92%(store+qd2), stressor stress-ng. **1b는 Net·Block 강도 sweep 추가측정 진행 중.**
> 상태(2026-06-19 갱신): **오버헤드를 4-figure 체계로 확장** — overhead_resource(자원,메인) + overhead_eventrate(이벤트율,보조) + **overhead_nodeload(노드부하,신규)** + **overhead_e2e(with/without,신규)**. 오버헤드를 **(a) 함수 critical-path 지연 / (b) 프로세스 자원**으로 분해. overhead_e2e는 이전 HPDC 리뷰어의 "음수 오버헤드" 지적에 대응해 **OFF/ON paired t-test "통계적 무차별"**로 입증(절댓값 금지). overhead_eventrate에 한때 넣었던 measured real-function 밴드는 **롤백**. fig1a/3/4/5/6/7 가독성(legend·폰트·y축) 정리.

---

## 공통 규칙 (모든 figure 적용)

### 색 (§3 figure와 일관 — 색만 봐도 의미 인지)
- **회색/검정** = Solo G.T. (조용한 노드 solo run, 정답·기준선)
- **파랑** = Pure (PureTime 출력 = 순수 실행 시간 / 보존)
- **빨강** = E2E with stress (노이즈 낀 실측 = `T_wall`)
- **주황** = naive (병합 안 한 단순 합 — figure 2 전용)

### Y축 정규화 규칙
- **solo 정규화 (solo=1.0)**: figure 1a, 1b, 2
  - "Pure가 1.0에 붙는다"가 강점으로 또렷, 자원/스케일 통일
  - Block 잔여 갭은 E2E 대비로 자연스럽게 완화
- **절대 ms**: figure 3, 4, 5
  - 날뜀·band·on/off 차이를 자연스럽게 보임

### 차트 형태 규칙
- **box plot** (분포 보임, K=50): 1a, 5 — "분포 겹침으로 판정" 방법론 반영
- **line**: 1b, 2
- **시계열**: 3, 4

### 반복
- 모든 측정 **K=50**. box는 분포 그대로, line/시계열은 점=중앙값 + 음영=IQR(또는 분포 폭).

### 정직성 원칙
- 정규화는 강점을 또렷하게 보이는 정당한 선택이되 **거짓 아님**.
- Block 잔여 오차는 figure에 그대로 보이고, 캡션·본문에서 "스케줄러 큐 경합만 제거, 장치 dilation은 범위 밖(§7)"이라 설명.
- figure는 강점을 강조하되 리뷰어 질문에 *이미 본문에 답이 있게*.

### 공통 testbed (실험 설계 파일 기준)
- cgroup v2 격리 컨테이너로 서버리스 함수 실행 환경 재현 (Knative 미배포)
- core 0 제외 + victim/stressor 코어 핀 고정, victim 단일 스레드 (**예외: Figure 2 interval-merge만 동시 2-스레드** — 겹치는 wait을 만들려면 진짜 동시성 필요; CPU-경합 스레드는 단일 코어 핀이라 모델 가정 유지), NIC offload off
- 모든 노이즈 환경의 G.T. = 조용한 노드의 solo run **분포** (점이 아니라 분포; 판정은 분포 겹침/2-표본 검정)

---

## Figure 1a — 자원별 정확도 ✅

- **label**: `fig:eval-accuracy`
- **claim**: C1
- **레이아웃**: 1단 (single column)
- **증명**: 단일 자원 경합에서 Pure가 solo G.T. 분포에 수렴 (자원 3종 한눈에)
- **형태**: grouped box plot
- **X축**: victim 함수 3그룹 — `float`(CPU) / `upload`(Network) / `compression`(Block)
- **Y축**: solo 정규화 (solo 중앙값=1.0), 단위 없음(배수)
- **그룹당 3박스** (K=50 분포):
  - Solo G.T. (회색) — 정규화 기준이라 1.0 근처에 폭만
  - Pure with stress (파랑)
  - E2E with stress (빨강)
- **데이터**: 자원당 K=50 × 3값. **고정 강도 1개** (wall ≈ solo의 1.7×, 캡션 명시)
- **핵심 메시지**:
  - 각 그룹에서 **파랑(Pure)이 회색(Solo)≈1.0에 겹치고, 빨강(E2E)은 1.5+로 뜸**
  - CPU·Network는 거의 완벽 (≥80% 제거 → Pure≈1.0~1.1)
  - Block은 Pure가 *1.0에 가깝지만 약간 위* (~1.1~1.2, 잔여 dilation)
- **캡션 정직 문구**: "Block의 Pure가 Solo에 완전히 수렴하지 않는 것은 PureTime이 스케줄러 큐 경합만 제거하고 장치 내부 dilation은 범위 밖이기 때문(§7)."

---

## Figure 1b — 강도별 robustness ✅ (CPU·Net line + Block 대표 점)

- **label**: `fig:eval-robustness`
- **claim**: C2
- **레이아웃**: 1단
- **형태**: line chart, **X축 = slowdown(wall/solo) = 경합 강도**, **Y축 = removal%**(= (E2E−Pure)/(E2E−solo), 제거된 노이즈 비율). robustness는 **removal%**로 본다 — nf/solo는 같은 잔차를 slowdown 배수만큼 증폭해 (removal이 일정해도) 우상향처럼 보이므로 부적합.
- **세 자원** (2026-06-17/18 측정): **CPU**(stress worker 1/3/7) **99/98/98% @ 1.76/2.25/3.03×** — 거의 100% 평탄. **Network**(iperf3 -P 4/6/8) **90/87/83% @ 4.69/6.51/8.37×** — 의미있는 경합에서 ≥83% robust. (강도2(-P2, wall 2.85×)는 약한 경합이라 net wait이 작아 TCP backoff 잔차 비율↑로 72%로 낮아 **제외** — §7. 또 연속 network 측정은 후반 run에서 socket→cgroup attribution이 누락되는 이상치가 생겨, 강도6은 attribution 성공분만 사용.) **Block**(fio job 4) **91% @ 3.15× — 단일 대표 점**(line 아님): block removal은 HDD 물리 상태(채워진 디스크 91% ↔ 빈 디스크 45%, 둘 다 std 7~8로 내부 안정 → 디스크 *상태* 차이지 노이즈 아님)에 좌우돼 강도 sweep을 동일 디스크 상태로 통제 불가(§7 + CLAUDE.md "filled HDD" 전제). 그래서 1a의 대표 점만 찍고 "disk-dependent" 주석 — 3자원을 다 보여 1a와 대칭을 유지하되 block의 디스크 의존성은 정직하게 드러낸다.
- **데이터 소스**: CPU·Block = `accuracy_K50/accuracy_results.csv`, Network = `robustness_1b/results.csv` (pairwise: 같은 iteration의 solo로 정규화). plotter `plot_exp1b_robustness.py` → `robustness.pdf`.
- **증명**: 강도↑(slowdown 1.8→8.4×)에도 removal이 무너지지 않고 유지(CPU ~98%, Net 70~90%, Block 91%).
- **형태**: line chart (자원별 색 또는 panel 3개)
- **X축**: **slowdown 배수** (solo 대비 wall, 1.0×·1.3×·1.7×·2.0×...) — 자원 단위 차이를 한 축으로 통일
- **Y축**: solo 정규화 (solo=1.0)
- **세 선** (각 강도 = K=50 중앙값, 음영=IQR):
  - E2E (빨강) — 우상향 (강도↑ 노이즈↑)
  - Pure (파랑) — solo에 붙어 수평
  - Solo G.T. (회색 점선) — 1.0 상수
- **핵심 메시지**:
  - **빨강 우상향으로 벌어지는 동안 파랑은 1.0에 붙어 수평**
  - 둘 간격 = 제거한 노이즈
  - Block panel은 파랑이 1.1 근처에서 수평 (잔여 일정 비율)

---

## Figure 2 — interval-merge 효과 ✅ ★novelty

- **label**: `fig:eval-merge`
- **claim**: C3
- **레이아웃**: 1단
- **증명**: 다자원 동시 경합에서 (1) Pure 정확 (2) 그게 merge 덕분 — naive는 겹침↑ 따라 과다제거로 발산
- **형태**: line chart
- **victim (★ 동시 경합 — 단일스레드 아님)**: `video_processing`(numpy 흑백 변환 + boto3 업로드). interval-merge는 **둘 이상 자원의 wait이 시간상 겹칠 때만** 의미가 있는데, 단일스레드는 자원을 직렬화(선점 중이면 I/O 대기 아니고, 막혀 있으면 runnable 아님)해 CPU wait ∩ Net wait 겹침이 ≈0이다. 따라서 이 victim만 **동시 2-스레드 + 스레드별 CPU affinity**: `cpu_worker`(grayscale)→경합 코어(CPU wait), `net_worker`(MinIO sustained 업로드)→빈 코어(Net wait). 한 cgroup에서 두 wait이 **동시 발생**해 겹친다.
  - **자원 조합 = CPU + Net** (둘 다 잘 포착, 정확도 98%/89%). **Block 제외**: `block_rq_issue`가 dispatch 시점이라 `[issue→complete]` 장치 service-time(범위 밖)이 슬로다운을 지배 → Pure가 solo 위로(과소제거) 가고 naive가 오히려 solo에 가까워져 **스토리가 역전**된다(실측 확인). CPU+Net으로 한정해야 깨끗한 정방향 곡선.
- **X축**: **겹침 비율 = (naive_sum − merged) / naive_sum**, 범위 0~1
  - **`naive_sum` = 자원별 wait의 단순 합 Σ(cpu, net)**, `merged` = 그 wait들의 합집합(union) 길이. 겹침 = Σ − union.
  - 0 = 안 겹침(Σ=union), 1에 가까울수록 대부분 겹침. CPU-경합 강도를 sweep해 겹침 비율 분포(8→30%).
- **Y축**: solo 정규화 (solo=1.0). (= noise_free / solo; naive는 `makespan − naive_sum`, merge는 `makespan − union` 기준)
- **네 선** (강도별 점, K):
  - Solo G.T. (회색 점선) — 1.0
  - E2E (빨강) — 1.0 위로 떠 있음
  - **Pure with merge (파랑)** — 겹침 비율 무관 1.0 근처 수평 (실측 0.78~1.07)
  - **Pure without merge = naive (주황 점선)** — 겹침 0에선 merge와 일치(만남), 겹침↑ 따라 1.0 *아래로 발산*해 **0 밑(음수)**까지 (실측 0.79→−0.41)
- **기준선**: y=1.0 (정답) + **y=0 (물리적 하한)** 둘 다 그어 강조
- **핵심 메시지**:
  - **파랑(merge)은 1.0에 수평, 주황(naive)은 겹침↑ 따라 아래로 발산해 0(음수)까지**
  - 둘의 갈라짐 = merge 기여 / 음수 구간 = naive의 물리적 불가능(혼자보다 빠름) → merge 필요성의 강력한 증거
- **본문 연결**: naive는 여기서 처음 등장 (§4.3에서 의도적으로 뺐음). "병합 없이 자원별 wait를 단순 합산(Σ)한 값과 비교"로 도입 (cherry-pick 의심 회피)

---

## Figure 3 — 동적 입력 흐름 추종 ✅

- **label**: `fig:eval-input-dynamic`
- **claim**: C5
- **레이아웃**: 1단 (또는 4와 함께 2단 가능)
- **증명**: 입력을 랜덤 셔플하면 시간이 날뛴다. Pure가 *입력 때문에 변해야 할 흐름(solo)을 정확히 추종*, 노이즈만 제거
- **형태**: 시계열 (line 또는 line+marker)
- **X축**: **호출 순서 (1~30)** — 입력 랜덤 셔플 순서
- **Y축**: **절대 ms** (정규화 X — solo가 평평해지면 날뜀이 안 보임)
- **세 선**:
  - Solo G.T. (회색) — 입력 랜덤이라 위아래로 날뜀 (따라가야 할 정답 흐름)
  - E2E with stress (빨강) — solo 위 + 더 심하게 날뜀 (입력+노이즈 섞임)
  - Pure with stress (파랑) — **회색에 포개져 같이 날뜀** (입력 변동 유지, 노이즈 제거)
- **데이터**:
  - 입력 6~8종 (얼굴 수 0/1/5/10/15/30 + float) K=50 측정값 → **30개 랜덤 셔플 시퀀스**
  - 대표 시드 고정, 캡션 명시
  - CPU stress 고정
  - **band·통계 요소 없음**
- **핵심 메시지**:
  - **세 선 다 날뛰는데 파랑이 회색에 포개지고 빨강만 위로 더 출렁**
  - 수평이 아니라 *같이 날뛰면서도 정답에 붙는다* = input-invariance의 동적 증명
  - 통계 평균은 이 날뜀을 뭉개 불가능

---

## Figure 4 — 통계 baseline 실패 ✅ ★

- **label**: `fig:eval-baseline`
- **claim**: C6·C8·C9
- **레이아웃**: 1단 (KPA 분리 시) 또는 2단
- **증명**: *같은 동적 흐름*에서 통계 방법(mean±2σ, KPA)은 오작동, PureTime은 정확
- **형태**: 시계열 + band overlay (Figure 3과 동일 30회 데이터)
- **X축**: **호출 순서 (1~30)** — Figure 3과 동일 시퀀스
- **Y축**: **절대 ms** (band가 절대값 기준)
- **그릴 것** (겹쳐서):
  - Solo G.T. (회색), E2E (빨강), Pure (파랑) — Figure 3과 같은 세 흐름
  - **mean ± 2σ band** (AWS CloudWatch Anomaly Detection 기본): 과거 wall 기준. 음영 band
  - **E2E가 band 넘는 점 = false alarm**: 빨강 점에 강조 마커 (예: 빨강 원/X)
  - Pure는 band 안 + 각 solo에 붙음
- **핵심 메시지**:
  - **E2E(빨강)가 band를 자주 넘음 = false alarm (노이즈로 오판)**
  - **Pure(파랑)는 band 안 + 정확**
  - band가 넓음(E2E 분산 커서) → 진짜 회귀 놓침; Pure 기준이면 band 좁아 빨리 잡음
- **KPA autoscaling — 별도 처리** (한 figure 과밀 방지):
  - **옵션 A (추천)**: 별도 작은 panel/inset
    - y = 요청당 처리시간 → concurrency (Little's Law 환산)
    - threshold 수평선 70/pod (containerConcurrency 100 × util 70%)
    - E2E 기반은 70 넘김 (over-provision, 가짜 pod = ⌈부푼/70⌉−⌈진짜/70⌉)
    - Pure 기반은 미만
  - **옵션 B**: 본문 수치/표로만 서술
- **캡션 정직 문구**: "결정 대조(2σ band, KPA 70)는 측정값과 실제 기본 임계값으로 환산한 *counterfactual 서술*이며, 폐루프는 구동하지 않음(future work)."

---

## Figure 5 — 오버헤드 (4-figure 체계) ✅

> **핵심 프레임 (2026-06-19 확정): PureTime 오버헤드 = (a) 함수 critical-path 지연 + (b) 프로세스 자원**
> - **(a) 함수 지연** = 함수 *자신*의 커널 이벤트율에 비례. 별도 userspace loader가 ring buffer를 비우므로 critical path엔 가벼운 훅(reserve/submit)만 남아 본질적으로 작다. → fig3(이벤트율 곡선)·fig3-2(노드부하 flat)·fig_overhead_e2e(실측 ON/OFF)로 입증.
> - **(b) 프로세스 자원** = loader가 *노드 전체*(이웃 co-tenant 포함) 이벤트를 추적·드레인하는 CPU/RSS. `sched_switch`가 전역 tp_btf 훅이라 노드 부하에 비례. → fig4로 <0.1% 입증.
> - 바쁜 노드(PureTime이 *필요한* 상황)의 비용은 (b)가 흡수하고 개별 함수 (a)는 작게 유지 — "바쁘면 오버헤드↑ → 가치명제 붕괴" 우려의 정면 해소.

### Figure 5-메인 — 자원 footprint `overhead_resource.pdf`

- **label**: `fig:eval-overhead`
- **claim**: C7
- **레이아웃**: 1단 (2-패널 막대)
- **증명**: PureTime의 online 비용(트레이서 CPU% + RSS)이 멀티테넌트 노드 자원의 **0.1% 미만** — 가볍고 ring buffer로 조절 가능.
- **★ 왜 "자원"이 메인이고 "시간 오버헤드"가 아닌가 (시스템 논문 관행)**: PureTime 시간 오버헤드는 별도 userspace 프로세스(loader)가 ring buffer를 비우므로 함수 critical path에는 가벼운 커널 훅(reserve/submit)만 남아 **측정 노이즈 이하(<1%)**다. 따라서 실제 비용은 PureTime 프로세스가 노드에서 차지하는 *자원*이며, 그것을 메인 figure로 보인다. (시간 오버헤드를 box plot으로 victim 절대시간 with/without 비교하려 했으나 오버헤드<측정노이즈라 세션마다 부호가 바뀌어 실패 — 시간 오버헤드를 *메인 지표*로 내세우는 것 자체가 부적절. 곡선은 그 스케일링을 보이는 *보조*다.)
- **형태**: 2-패널 막대, Y축 = **% of node resource** (작게 보여 "낮음"을 정직 시각화; 0.1% 기준선)
  - **(a) CPU**: victim 3종(`float`/`upload`/`compression`), 노드 24코어 대비 **0.05~0.08%**(= 한 코어의 1~2%; 이벤트율 따라 victim별 차이 — float이 switch 많아 최고). 막대 라벨에 한 코어% 병기.
  - **(b) Memory(RSS)**: **단일 막대**(victim 무관 일정), 노드 RAM(94GB) 대비 **0.075%**(= ~71MB). ring buffer 크기가 지배(32MB 측정 빌드; 512MB 기본 → ~1GB) → 조절 가능.
- **online만**: eBPF hooks + Loader. **Analyzer 제외**(offline, critical path 밖) 캡션 명시.
- **측정 빌드**: `events` 맵 32MB(RSS ~71MB). 512MB 기본(RSS~1GB) 아닌 *측정용*임을 캡션 명시.
- **파일**: `overhead_resource.pdf` (plotter `plot_overhead_resource.py`; 옛 시계열 스파이크 plot은 폐기).

### Figure 5-보조 — 시간 오버헤드 스케일링 (이벤트율 곡선)
- **claim**: C7 (보조). PureTime 시간 오버헤드는 추적하는 **커널 이벤트 수에 비례**한다. 실제 함수 절대시간으론 노이즈 이하라 직접 측정이 불안정하므로(box plot 실패의 근본 이유), **이벤트율(switch/s)을 x축으로 sweep**해 "오버헤드 ∝ 이벤트율" 곡선으로 보조 제시 — victim=`ctxsw-bench`(부모-자식 pipe 핑퐁: sched_switch를 결정적 생성, 같은 코어 협력 실행이라 CPU 경쟁 노이즈 없음). 현실 함수율(~12K switch/s)에서 <1%, 극단(717K)에서도 곡선상 예측 가능. 메인(자원)의 "시간 오버헤드가 왜 작은지"를 정량 뒷받침.
- **파일**: `overhead_eventrate.pdf` (`plot_overhead_ctxsw.py`). inset/appendix 또는 본문 보조.
- ⚠️ **measured real-function 밴드 롤백(2026-06-18)**: 한때 "실제 함수는 39~840 switch/s 저영역"이라 음영+화살표를 넣었으나 — (1) `/var/log/puretime` 트레이스가 통제 안 된 테스트라 신뢰 불가, (2) "함수 한가 → 오버헤드 0" 프레이밍이 PureTime 가치명제(바쁜 노드 노이즈 제거)와 모순 — 으로 **전부 롤백**. 대신 fig3-2/e2e로 (a)/(b) 분리를 정직하게 입증. (자세히: 메모리 `fig3-real-function-event-rates`.)

### Figure 5-보조2 — 시간 오버헤드 vs 노드 부하 (신규, 2026-06-19) `overhead_nodeload.pdf`
- **claim**: C7 (보조). plotter `plot_overhead_nodeload.py`, 실험 `exp_overhead_nodeload.sh`, 데이터 `data/overhead_nodeload/results.csv`.
- **X**: 노드 전체 이벤트율(×1000 switch/s) — 배경 co-tenant 컨테이너(ctxsw-bench) 0→10개를 victim과 *다른 코어*에 띄워 노드 부하를 33K→619K/s로 sweep. victim 율은 고정. **Y**: victim 시간 오버헤드 %, median + IQR + 개별점. `dropped_events>0` 레벨은 빨간 테두리(PureTime이 못 버티는 한계).
- **메시지**: ring buffer가 전 CPU 공유 단일 맵(스핀락 1개, `puretime.bpf.c:21-24`)이라 노드 부하가 victim 지연으로 새는 결합 항이 *존재*하지만 실측상 무시 수준 — **노드 19배(33K→619K/s) 바빠도 victim 오버헤드 baseline(~2.2%) 근처 flat, drop=0**. 위 (a)/(b) 분리의 실측 입증. K=20, **median 필수**(경쟁 노이즈로 평균은 outlier에 망가짐). drop 영역까지는 안 감(ring full→빠른실패 flat이라 해석 지저분; drop=0 범위가 정직).

### Figure 5-대안 — 실제 victim with/without e2e (신규, 2026-06-19) `overhead_e2e.pdf`
- **claim**: C7 (대안 시간측정, Clover식). plotter `plot_overhead_e2e.py`, 실험 `exp_overhead_e2e.sh`, 데이터 `data/overhead_e2e/results.csv`.
- **형태**: victim 3종(cpu=`float` / block=`compression` / net=`network-uploader`) solo를 PureTime ON/OFF로 K=30 측정(counterbalance). **Y = 실행시간(OFF=100% 정규화)**, victim별 OFF/ON 두 막대 + 95% CI. y축 70~130(100% 중앙)으로 1% 차이가 시각적으로 미미. p-value/수치 라벨은 figure에서 생략(본문/캡션에).
- **메시지**: ON/OFF 실행시간이 **통계적으로 구별 안 됨** — paired t-test CPU p=0.38 / Net p=0.74 (n.s.), Block만 +1.1%(p=0.03, block_rq 이벤트 추적 비용으로 작게 유의).
- **★ HPDC "음수 오버헤드" 대응 (정직성 핵심)**: overhead=(with−without)/without 비율은 오버헤드<측정노이즈라 부호가 음/양 섞여 이전 HPDC 리뷰어가 "음수 오버헤드(PureTime 켜면 더 빠름)"를 지적했음. **절댓값 |Δ|/without 금지**(half-normal 상향편향으로 노이즈를 가짜 양수 오버헤드로 둔갑 — 리뷰어 red flag). 대신 overhead%를 안 그리고 OFF/ON 시간 직접 비교 + paired t-test "n.s."로 → 음수라는 단어/방향 없이 "통계적 무차별" 입증. 본문은 "오버헤드 거의 없음"보다 **"통계적으로 유의하지 않음"**으로(raw 요구받아도 떳떳). (자세히: 메모리 `puretime-overhead-e2e`.)
- ⚠️ 경쟁 주입(`exp_overhead_e2e_cpustress.sh`: stress-ng로 victim 양수화 시도)은 victim 실행시간 출렁임으로 overhead CI가 solo의 ±1.3%→**±5.27%** 폭증해 역효과 → **폐기**(solo가 CI 좁아 우월).

---

## 전체 요약표

| # | label | 형태 | X축 | Y축 | claim | 레이아웃 | 상태 | 실제 생성 파일 |
|---|---|---|---|---|---|---|---|---|
| 1a | `fig:eval-accuracy` | box | victim 3종 | 정규화 | C1 | 1단 | ✅ | `accuracy_baseline.pdf` |
| 1b | `fig:eval-robustness` | line+점 | slowdown 배수 | removal% | C2 | 1단 | ✅ | `robustness.pdf` (CPU·Net line + Block 대표점) |
| 2 | `fig:eval-merge` | line | 겹침비율 (Σwait−union)/Σwait | 정규화 | C3 | 1단 | ✅ | `interval_merge_scatter.pdf`·`interval_merge_bars.pdf` |
| 3 | `fig:eval-input-dynamic` | 시계열 | 호출순서 1~30 | 절대 ms | C5 | 1단 | ✅ | `input_variance_float.pdf`·`input_variance_face.pdf` |
| 4 | `fig:eval-baseline` | 시계열+band | 호출순서 1~30 | 절대 ms | C6·8·9 | 1단(+KPA분리) | ✅ | `baseline_cloudwatch.pdf`·`baseline_kpa.pdf` |
| 5 | `fig:eval-overhead` | 막대(2-패널) | victim 3종 | % of node | C7 | 1단 | ✅ | `overhead_resource.pdf` (자원 메인) |
| 5-보조 | — | 곡선 | switch/s | overhead% | C7 | 보조 | ✅ | `overhead_eventrate.pdf` (이벤트율) |
| 5-보조2 | — | 곡선(median+IQR) | 노드 switch/s | overhead% | C7 | 보조 | ✅ 신규 | `overhead_nodeload.pdf` (노드부하 flat, drop=0) |
| 5-대안 | — | 막대+95%CI | victim 3종 | 실행시간%(OFF=100) | C7 | 대안 | ✅ 신규 | `overhead_e2e.pdf` (ON/OFF paired t-test, n.s.) |

- **개수**: figure 6개(1b 포함) + 오버헤드 보조 곡선 1개. §5 ~3.5pp에 적정.
- **✅ 파일명 정리 완료(2026-06-19)**: 파일명을 내용 기반 이름으로 변경해 Overleaf `\label{fig:...}`과 일치시킴(넘버링 제거). 위 표의 "실제 생성 파일" 열이 최종 이름.
- **Figure 5 결정(2026-06-18)**: 오버헤드 메인 = **자원 footprint(overhead_resource: CPU%/RSS, % of node)**, 시간 오버헤드는 critical-path 분석 + 이벤트율 곡선(overhead_eventrate ctxsw) **보조**. box plot은 시간 오버헤드(<1%)가 측정 노이즈보다 작아 세션마다 부호가 바뀌어 **폐기**(부하·throttle·K 조정 다 실패 — 시간 오버헤드를 *메인 지표*로 내세우는 게 PureTime엔 부적절; 별도 프로세스라 critical path 비용이 본질적으로 작음). 곡선(ctxsw)은 *보조*로 유지(폐기 안 함).

---

## 데이터 재사용 관계 (실험 설계 파일 기준)

- 실험 4 = 실험 3 데이터 셔플 (추가 실험 없음)
- merge ablation (figure 2의 naive) = 실험 2 데이터 (별도 캡처 없이 같은 trace를 merge on/off 두 경로로 분석)
- (실험 2 ⊃ 실험 1은 **폐기**: 실험 2는 CPU+Net 동시-경합 전용 victim/sweep이라 단일-노이즈 데이터를 재사용하지 않음)

---

## victim 함수 (실험 설계 파일 기준)

- **CPU** = `float` (register/L1-bound sqrt/sin/cos 루프 — IPC dilation 누수 없음)
- **Block I/O** = `compression` **store 모드** (`COMPRESS_METHOD=stored` = zip 무압축 = archiving, I/O-bound). **측정 전제 2개**: (1) **`queue_depth=2`** — 기본 depth=32에선 NCQ가 경합을 `[issue→complete]` 장치 service-time에 숨겨 39%만 제거; depth=2가 경합을 OS 스케줄러 큐(`insert→issue`, 포착됨)로 직렬화. (2) **HDD가 현실적으로 채워진(단편화) 상태** — 빈 디스크는 I/O가 빠른 트랙에 연속 배치돼 경합이 큐에 안 쌓여 removal이 45%로 떨어진다(둘 다 내부 std 7~8로 안정 → 디스크 *상태* 차이지 노이즈 아님). 실제 서버리스 노드 디스크는 채워져 있으므로 채워진 상태가 현실적이고, 그때 **~91% removal @ 3.2× (K=50, nf/solo 1.20)**. (순수 `dd`는 이 전제들 없이는 디스크 포화→seek dilation으로 깨짐.)
- **Network** = cloud storage **업로드** (PureTime은 TX만 추적 → 업로드 경로)
- **Mixed** (실험 2) = `video_processing` (numpy+boto3) — **동시 2-스레드 + 스레드별 affinity**(`cpu_worker` grayscale + `net_worker` MinIO sustained 업로드). CPU+Net만(Block 제외, Figure 2 참조).
- **Input-variant** (실험 3) = `float` + face detect+sentiment 파이프라인 (얼굴 수 0/1/5/10/15/30)

## stressor (실험 설계 파일 기준)

- **CPU** = `stress-ng --cpu-method float` (register/L1-bound, 별도 cgroup, taskset 경합 코어) — 메모리 대역폭 미경합 (on-CPU IPC dilation 누수 차단; dilation은 범위 밖)
- **Block** = `fio` 쓰기 (BFQ + queue_depth=2)
- **Network** = `iperf3 -c` (TCP, 별도 level≥2 cgroup), 강도 = `-P` 병렬 flow 수 (TCP만, UDP 미추적)

---

## 실측 결과 요약 (참고 — 본문 수치는 최종 데이터로 갱신)

- **CPU**: ~98% @ 1.0→3.1× (강도 sweep)
- **Network**: ~89% @ 4.8× (강도 sweep 4/6/8: 90/87/83%, robust; 약한 강도2는 72%로 제외)
- **Block**: ~91% @ 3.2× (K=50, nf/solo 1.20; **store 모드 victim + queue_depth=2 + 채워진 HDD 전제**). 전제가 깨지면 떨어짐: 기본 depth=32 → 39%, 빈 디스크 → 45%. 과다제거 꼬리 ~13% + `[issue→complete]` 장치 dilation은 범위 밖(§7) 정직 명시
- → **세 자원 모두 ~89~98% removal** (Block은 전제 충족 시)

---

## figure 가독성 정리 (2026-06-18~19)

전체 §5 figure의 legend·폰트·레이아웃을 논문 게재(column 축소) 기준으로 정리:
- **fig1a**: y max 38000, label·legend 텍스트 확대, Tableau muted 색, hatch 제거
- **fig3**: 폰트·마커·선 확대, inset 우측 재배치 + 폰트 확대, 메인은 끝점(+44.4%)만 라벨
- **fig4**: legend·라벨 확대 (보라 계열)
- **fig5a/b · 6a/b · 7a/b**: 타이틀 제거 + a/b 분리 + legend 크기·배치 정리 (fig7 legend 2줄 배치 + 순서 보정)
- **fig_overhead_e2e**: y 70~130(100% 중앙)으로 ON/OFF 차이 시각적 미미, p-value/수치 라벨 제거
- 원칙: figure는 시각적 경향, 정확 수치는 본문/표 — 모든 막대에 수치 라벨 의무 없음. 단 "통계적 무차별(n.s.)" 같은 *결론 근거*는 figure나 본문에 반드시 명시(음수 숨기기가 아니라 정당한 통계 결론이 되도록).

---

## 마스터 매핑 (figure ↔ plotter ↔ 실험 ↔ 데이터 ↔ claim)

| Figure (PDF) | plotter | 실험 스크립트 | 입력 데이터 | claim |
|---|---|---|---|---|
| `accuracy_baseline` | `plot_evaluation.py` → `fig_accuracy_baseline` | `exp_accuracy_by_type.sh` | `accuracy_K50/accuracy_results.csv` | C1 (+C2) |
| `robustness` | `plot_exp1b_robustness.py` | `exp_accuracy_by_type.sh` (강도 sweep) | `accuracy_K50/` (CPU+Block) + `robustness_1b/results.csv` (Net) | C2 |
| `noise_source_id` | `plot_evaluation.py` → `fig_noise_source_identification` | `exp_accuracy_by_type.sh` | `accuracy_K50/accuracy_results.csv` | C2 |
| `overhead_eventrate` | `plot_overhead_ctxsw.py` | `exp_overhead_ctxsw.sh` | `overhead_ctxsw/results.csv` | C7 (시간·보조) |
| `overhead_nodeload` | `plot_overhead_nodeload.py` | `exp_overhead_nodeload.sh` | `overhead_nodeload/results.csv` | C7 (노드부하) |
| `overhead_resource` | `plot_overhead_resource.py` | `exp_overhead_resource.sh` | `overhead/overhead_resource.csv` | C7 (자원·메인) |
| `input_variance_float`/`input_variance_face` | `plot_exp3_input_variance.py` | `exp_input_variance.sh` | `input_variance/results.csv` | C5 |
| `baseline_cloudwatch`/`baseline_kpa` | `plot_exp4_baseline.py` | (실험3 데이터 재사용, 별도 run 없음) | `input_variance/results.csv` | C6/C8/C9 |
| `interval_merge_scatter`/`interval_merge_bars` | `plot_exp2_interval_merge.py` | `exp_mixed_noise.sh` | `mixed_noise/results.csv` | C3 (novelty) |
| `overhead_e2e` | `plot_overhead_e2e.py` | `exp_overhead_e2e.sh` | `overhead_e2e/results.csv` | C7 (대안 시간) |

혼동 주의:
- `plot_evaluation.py`는 **accuracy_baseline·noise_source_id** 생성기. 그 안의 `fig_overhead_time()`/`fig_overhead_resource()`는 **deprecated**(standalone `plot_overhead_*`가 대체). `plot_fig1_architecture.py`는 시스템 아키텍처 다이어그램(평가 figure 아님).
- `overhead_eventrate.pdf`의 plotter는 `plot_overhead_ctxsw.py`(이벤트율 곡선)다.
- `exp_overhead_time.sh`는 **deprecated**(graph-bfs ON/OFF 절대시간 → 음수 오버헤드; `exp_overhead_ctxsw.sh`로 대체).
- ✅ 파일명은 내용 기반(넘버링 제거)으로 정리돼 Overleaf `\label{fig:...}`과 일치(2026-06-19).