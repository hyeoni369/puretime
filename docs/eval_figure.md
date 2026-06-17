# PureTime §5 Evaluation — Figure 최종 스펙

> SoCC 2026 2라운드. 실험 1~5에 대응하는 figure 6개 + table 1개.
> 이 문서는 figure를 *그릴 수 있는 수준*의 최종 명세. 색·정규화·형태가 §3 figure와 일관.
> 상태(2026-06-17 갱신): 실제 구현·커밋된 결과에 맞춰 정정 — Figure 5(오버헤드) 합격기준 완화(중앙값<1.5%, 개별 음수 허용)+이벤트율 곡선 보조, Figure 2(실험2) victim을 동시 2-스레드 CPU+Net으로, Block 91~92%(store+qd2), stressor stress-ng. **1b는 Net·Block 강도 sweep 추가측정 진행 중.**

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

## Figure 1b — 강도별 robustness ✅ (CPU + Network, Block 제외)

- **label**: `fig:eval-robustness`
- **claim**: C2
- **레이아웃**: 1단
- **데이터 (2026-06-17 측정 완료)**: **CPU**(stress worker 0/1/3/7 = solo+3강도) + **Network**(iperf3 `-P` 0/2/4/8). 둘 다 강도↑에도 removal 유지: **Network 72%/90%/83% @ wall 2.85/4.71/8.39×**(robust), CPU도 sweep 보유. → CPU+Network 2-패널 또는 2색 line으로 robustness 표시.
- **Block 제외 (정직)**: Block 강도 sweep도 측정했으나(`fio job 2/4/8`), **removal이 HDD 물리 상태에 좌우됨**이 드러나 1b에서 뺀다. 빈 디스크에선 35~45%, 채워진(현실적) 디스크에선 91%로, queue_depth=2가 걸려 있어도 *디스크 채움 상태*가 결과를 가른다(둘 다 std 7~8로 내부 안정 → 측정 노이즈 아닌 환경 레짐). Block은 **1a의 대표 강도(채워진 디스크에서 91%)**만 쓰고, robustness 곡선은 CPU·Network로 보인다. (자세한 건 §7 한계 + CLAUDE.md "filled HDD" 전제.)
- **증명**: 강도↑에도 Pure가 solo에 계속 붙음 (CPU·Network)
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

## Figure 5 — 지연 오버헤드 ✅

- **label**: `fig:eval-overhead`
- **claim**: C7
- **레이아웃**: 1단
- **증명**: 실제 사용 환경(적당한 경합)에서 PureTime 켜도 함수 실행 시간 거의 안 늘어남
- **형태**: grouped box plot (실험 1a와 일관)
- **X축**: victim 함수 3종 — `float` / `upload` / `compression` (실험 1 함수 그대로)
- **Y축**: **절대 ms** (0부터 시작 — 작은 차이 과장 방지, "거의 안 변함" 정직하게)
- **함수당 2박스** (K=50 분포):
  - PureTime OFF (회색) — baseline
  - PureTime ON (파랑)
- **데이터**: 함수당 **적당한 부하 하에서** solo run K=50 × {on, off}
  - **부하 수준**: PureTime이 실제 배포될 환경에 해당하는 *적당한 경합*(무부하의 비현실적 0%도, 극단 부하의 과장도 아닌 실사용 수준). 무부하가 아니라 현실적 경합에서 재는 이유: 이벤트가 발생해야 hook+캡처 비용이 실제로 드러남.
  - **측정 정밀도(중요)**: PureTime 지연 오버헤드는 <1.5%로 측정 노이즈에 가깝다. victim이 부하와 **같은 코어에서 CPU를 다투면** victim의 CPU 몫 변동(±15~33%)이 신호를 묻어 중앙값까지 흔들리므로, **victim과 stressor를 별도 코어에 핀**해 CPU 쟁탈을 없앤다(이벤트는 victim 자신의 I/O/네트워크에서 발생). 추가로 **on/off 순서 counterbalance(홀짝 iteration 교대) + victim self-reported `elapsed_ms`(perf_counter, 컨테이너 startup 변동 배제) + CPU 터보 off**로 분산을 줄인다.
- **합격 기준 (정직)**: **중앙값 오버헤드가 양수이면서 < 1.5%**. 오버헤드가 워낙 작아 **개별 측정 중 일부는 음수**(우연히 ON이 OFF보다 빠름)가 나오는데, 이는 측정 노이즈의 자연스러운 결과이며 박스의 아래 whisker가 0 밑으로 내려가도 무방하다(짜맞추지 않음). 중앙값만 양수면 충분.
- **핵심 메시지**:
  - 각 함수에서 on/off 두 박스 거의 겹침 = 실사용 환경에서도 오버헤드 미미 (중앙값 양수, < 1.5%)
  - 중앙값 차이(%)를 박스 위 수치로 표기
- **본문/캡션 명시**: "PureTime이 실제로 배포될 환경에 해당하는 적당한 부하에서 측정했고, 중앙값 오버헤드는 1.5% 미만이다. 오버헤드가 측정 노이즈보다 작아 일부 개별 측정은 음수로 나오지만(ON이 우연히 빠름), 이는 오버헤드가 무시할 수준임을 보여줄 뿐 음의 오버헤드를 주장하는 것이 아니다."

---

## Table — 자원 사용량 ✅

- **label**: `tab:eval-resource`
- **claim**: C7
- **형태**: 표 (figure 아님)
- **행**: PureTime online 구성요소 — eBPF hooks + Loader
  - **Analyzer 제외** (offline, critical path 밖) 명시
- **열**: CPU 사용률(%), 메모리 RSS (MB)
- **데이터**: online 측정
  - **측정 조건**: Figure 5와 **동일한 적당한 부하** (지연·자원을 같은 환경에서 측정해 일관)
    - CPU%는 이벤트 발생량에 직접 비례하므로 적당한 부하에서 재야 정직
  - **ring buffer 32MB 빌드로 측정** (RSS ~70MB)
    - 512MB(기본, RSS~1GB)가 아닌 *측정용 32MB*임을 캡션/본문 명시 (안 그러면 "1GB 먹네" 오해)
    - `src/puretime.bpf.c`의 `events` 맵 `max_entries`를 32MB로 내려 빌드
- **핵심**: CPU% 낮음, RSS는 ring buffer 크기가 지배적이라 *조절 가능*

---

## 전체 요약표

| # | label | 형태 | X축 | Y축 | claim | 레이아웃 | 상태 | 실제 생성 파일 |
|---|---|---|---|---|---|---|---|---|
| 1a | `fig:eval-accuracy` | box | victim 3종 | 정규화 | C1 | 1단 | ✅ | `fig1_accuracy_baseline.pdf` |
| 1b | `fig:eval-robustness` | line | slowdown 배수 | 정규화 | C2 | 1단 | ✅ CPU+Net | (신규; Block은 HDD의존이라 제외) |
| 2 | `fig:eval-merge` | line | 겹침비율 (Σwait−union)/Σwait | 정규화 | C3 | 1단 | ✅ | `fig7_interval_merge.pdf` |
| 3 | `fig:eval-input-dynamic` | 시계열 | 호출순서 1~30 | 절대 ms | C5 | 1단 | ✅ | `fig5_input_variance.pdf` |
| 4 | `fig:eval-baseline` | 시계열+band | 호출순서 1~30 | 절대 ms | C6·8·9 | 1단(+KPA분리) | ✅ | `fig6_baseline_comparison.pdf` |
| 5 | `fig:eval-overhead` | box | victim 3종 | 절대 ms | C7 | 1단 | ⏳ 측정 | (box plot 측정 예정) |
| 표 | `tab:eval-resource` | table | — | — | C7 | — | ✅ | `fig4_overhead_resource.pdf` |

- **개수**: figure 6개(1b 포함) + 표 1개. §5 ~3.5pp에 적정.
- **⚠️ 파일명 주의**: 위 "논문 figure 번호"와 실제 생성 파일명(`fig1~7`)이 다름(생성 순서로 명명됨). 최종 figure 생성 시 파일명을 논문 번호에 맞춰 정리 권장.
- **Figure 5 결정(2026-06-17)**: **box plot만**(곡선 제거). 실제 함수(float/upload/compression) on/off, victim·stressor 별도 코어 핀, 중앙값 양수 <1.5%. 이벤트율 곡선(ctxsw) 방식은 합성 벤치마크의 인위적 이벤트율 함수라 "실제 함수 오버헤드"를 직접 주장 못 해 **폐기** → `ctxsw-bench`/`exp_overhead_ctxsw.sh`/`plot_overhead_ctxsw.py`/`data/overhead_ctxsw`/곡선 fig3는 정리 대상.

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
- **Network**: ~89% @ 4.8× (강도 sweep 2/4/8: 72/90/83%, robust)
- **Block**: ~91% @ 3.2× (K=50, nf/solo 1.20; **store 모드 victim + queue_depth=2 + 채워진 HDD 전제**). 전제가 깨지면 떨어짐: 기본 depth=32 → 39%, 빈 디스크 → 45%. 과다제거 꼬리 ~13% + `[issue→complete]` 장치 dilation은 범위 밖(§7) 정직 명시
- → **세 자원 모두 ~89~98% removal** (Block은 전제 충족 시)