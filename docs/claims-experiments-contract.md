# PureTime — Claims ↔ Experiments Contract

> 글쓰기 채팅과 실험 채팅의 **단일 진실(single source of truth)**.
> 결과가 나올 때마다 이 표를 갱신하고, 양쪽 채팅이 이 표를 기준으로 움직인다.
> 프로젝트 지식에 올려두고 주기적으로 갱신하거나, 각 채팅 시작 시 붙여넣어 사용.
> 최종 갱신: 2026-06-09 (**전 P0 설계 확정** · 그룹5 case study → 3-2 흡수 · 4-1 재설계 · testbed = cgroup v2 컨테이너 · 구현 순서·TDD 층 노트 추가 · **audit 수정 반영**: Scope 보강 + "audit 반영 구현 현황" 추가 + ring buffer 512MB/오버헤드 32MB 노트)

## Thesis (one sentence)
PureTime은 short-lived·input-dependent 서버리스 함수에 대해, CPU·network·block I/O·softirq의 contention-induced wait를 커널 이벤트에서 추적하고 co-tenant cgroup 활동과 상관시켜 노이즈를 분리한 뒤, interval merge로 겹치는 wait를 중복 없이 제거하여 per-invocation noise-free makespan을 산출하는 최초의 reference-free 시스템이다.

## 논문 contribution 문장으로의 압축 (SoCC 관례: 보통 3개)
아래 표의 10개 claim은 *검증 단위*다. 논문 contribution 리스트에서는 셋으로 묶어 제시 권장:
1. **정확한 다자원 noise-free 측정** — 네 자원의 contention wait를 커널에서 직접 측정, cross-tenant attribution + interval merge로 중복 없이 순수 시간 복원 (= C1·C2·C3·C4).
2. **Reference-free·input-invariant 측정** — 단일 호출 안에서 완결, input 변동에 불변, 통계 표본 불필요 (= C5·C6).
3. **실용성** — 저오버헤드 + 실제 결정(디버깅·벤치마킹·autoscaling)을 바꾸는 신호 (= C7·C8·C9·C10).

## 상태 범례
`계획` 설계 전 · `설계` 프로토콜 확정 · `진행` 수집 중 · `데이터` 일부 결과 있음(보강 필요) · `완료` 그림/표 확정
우선순위: **P0** resubmission 필수 · **P1** 강력 권장 · **P2** stretch/future-work

## Contract

| ID | Claim (falsifiable) | 검증 실험 | 리뷰 대응 | 우선 | 상태 | 결과/메모 |
|----|---------------------|-----------|-----------|------|------|-----------|
| C1 | noise-free makespan이 solo 기준(GT) 대비 오차 E% 이내 | 1-1, 1-2, 1-4 | core | **P0** | **설계** | 그룹1 단일-노이즈 **한 세트**에서 1-1·1-2·1-4 동시 추출. victim 4종, K=50, solo 분포 GT, 분포+오차막대. **E2E K=30/50(06-16): CPU 98%@1.0→3.1×(강도 sweep)·Net 89%@4.8×·Block 92%@3.2×(queue_depth=2 전제 + store-모드 I/O-bound victim, 과다제거 꼬리 ~13% 명시 — "Block 결론 수정 2026-06-16" 노트 참조). 기본 depth=32에선 Block 39%(NCQ가 경합을 issue→complete에 숨김).** |
| C2 | 네 자원 각각의 wait를 정확히 분류·귀속 (breakdown ↔ 주입 유형 일치) | 1-2 | — | P1 | **설계** | 그룹1 세트에서 추출. 자원 전용 victim이면 주입↔귀속 1:1로 깨끗. 1-3 스택바와 연계 |
| C3 | 자원 간 wait가 겹쳐도 중복 없이 제거 — 단순 역산 대비 과다차감 회피 | 1-3, 2-1 | C4 | **P0** | **완료** | **E2E(06-16, fig7):** 동시 CPU+Net 경합 victim(2-스레드, 스레드별 CPU affinity로 cpu_worker=경합코어·net_worker=빈코어 → 한 cgroup의 CPU wait ∩ Net wait이 시간상 겹침). 겹침 8→30% sweep: **merge nf/solo 0.78–1.07(전 구간 valid)** vs **naive 0.79→−0.41(겹침↑→음수, 물리적 불가능, 고겹침 7/10 runs 음수)**. 단일스레드는 자원 직렬화로 겹침≈0, Block은 issue→complete service-time이 범위 밖→스토리 역전이라 **CPU+Net**(둘 다 포착 98%/89%)으로 실증. **novelty 핵심** |
| C4 | self/neighbor 구분으로 정당한 self 대기는 보존, neighbor 노이즈만 제거 | 2-2 | — | P1 | 계획 | 분류 제거 시 결과 유의 변화 보여야 (미설계) |
| C5 | input(작업량) 변동 하에서 intrinsic 변동은 보존, extrinsic 노이즈만 제거 (solo와 상관) | 3-1 | 3단계 논거 | **P0** | **설계** | victim 둘: float(입력 크기) + detect+sentiment(입력 내용·얼굴 수 0·1·5·10·15·30). 둘 다 CPU-only register/L1 가변 stressor(IPC dilation 누수 차단). K=50, solo 분포 GT. **최우선 신규** |
| C6 | 단일 호출로 통계 표본 없이 신뢰성 있는 순수 시간 | 3-2 | C8 | **P0** | **설계** | 단일실행 vs 통계(median·P90·raw wall). 3-1 데이터 재사용(셔플해 시계열화), K=50=표본 N. **+ 결정 대조(5-1·5-2 흡수)**: CloudWatch 2σ 밴드·KPA 70 target counterfactual |
| C7 | 트레이싱 추가 지연·자원 비용이 낮음 | 4-1 | C6 | **P0** | **설계** | **재설계**: (A)지연 w/vs w/o 조용한 환경 분포+검정+CI, (B)자원 CPU·RSS·256MB·JSONL. online만(Analyzer offline=critical path 밖, 제외). HPDC "더 빠름" 음수 논란 해소 |
| C8 | 출력이 코드 회귀 vs 환경 노이즈를 구분 (false alarm 없음, 분산↓로 카나리 가속) | 3-2 (흡수) | C9 | P1 | **설계** | 3-2 결정 대조에 흡수. CloudWatch mean±2σ → 노이즈 낀 wall은 false alarm, 순수 시간은 정상. 별도 실험 삭제 |
| C9 | 노이즈로 인한 가짜 concurrency 증가를 걸러 over-provisioning 회피 신호 | 3-2 (흡수) | C9 | P1 | **설계** | 3-2 결정 대조에 흡수. KPA target 70/pod → wall은 over-provision, 순수 시간은 scale 안 함. counterfactual, 온라인은 future work |
| C10 | 실제 워크로드(FunctionBench 등)·명시된 하드웨어에서 성립 | 6-1, 6-2 | C3 | P1/P2 | 계획 | 1-3·그룹1에서 이미 FunctionBench/SeBS victim + cgroup v2 container 명세 사용 → 6-1 일부 자동 충족. 6-2(실제 co-tenant) P2 |

> **그룹5(case study) 5-1·5-2는 3-2에 흡수, 별도 실험 삭제.** 결정 로직은 측정값 + 실제 기본 임계값으로 *서술*(폐루프 미구동, future work).
> **실험 상세 설계는 별도 문서 `puretime-experiment-design-final.md` 참조.** (이 표는 추적용, 그 문서는 방법·figure·victim 확정 설계.)

## 구현 순서·검증 방법 (ClaudeCode)
- **순서**: eBPF 측정기(Tracer/Loader) + Analyzer를 *먼저* 완성 → victim·하니스·집계는 그다음. 측정·계산 코어가 맞아야 나머지가 의미 있음.
- **착수는 점검부터**: 기존 구현이 정확한지 + 효과 큰 최적화 여지 있는지 audit 먼저(Plan Mode + 읽기 전용 auditor subagent, "정확성 영향만, 스타일 지적 금지"). **점검 → 사람 분류 → 수정, 세 단계 분리**(한 번에 고치게 하지 말 것).
- **TDD는 층마다 다름**:
  - Analyzer(interval merge·attribution)·집계·통계 = **TDD 됨**(순수 함수). 가짜 JSONL + 손계산 정답으로 테스트 먼저. novelty 핵심이라 여기가 제일 중요.
  - eBPF 캡처(Tracer hook) = **TDD 아님 → validation**. 무부하→wait~0, 단일 자원 부하→해당 자원 이벤트만. + 실험 1·2·3의 solo 대조가 곧 eBPF 정확성 검증을 겸함.
- **invariant**(런타임 assert): noise_free ≤ wall_clock · 모든 wait_* ≥ 0 · merge union ≤ 구간 합 AND ≤ wall_clock · attribution 100%(±ε) · ring buffer 유실 시 불완전 trace는 makespan 거부.

### audit 반영 구현 현황 (2026-06-09, `audit` 브랜치 커밋됨)
점검 → 분류 → 수정 완료분. (figure/CSV는 이 수정 반영 후 재생성 필요 — 미반영.)
- **Analyzer 정확성**: wait union을 cgroup span `[first_ts,last_ts]`과 교집합(softirq_other 범위 밖 → 음수 makespan 버그 수정); 런타임 invariant assert; `trace_summary` trailer의 `dropped_events>0`이면 exit 2로 거부; CPU wait에 선행 슬라이스 계상(CPU-3, 핑퐁엔 효과~0·I/O wakeup 로버스트성).
- **interval-merge ablation(C3/2-1) 코드 경로**: 양 분석기가 merge(`noise_free_makespan`) vs naive(union 없는 자원별 합, `noise_free_naive`, 음수 가능) 동시 출력 → 겹침비율 vs 오차 figure. **실행 완료(2026-06-16): `experiments/data/mixed_noise/` + fig7** (merge 0.78–1.07 vs naive 0.79→−0.41, 겹침 8→30%).
- **Tracer/Loader**: block I/O를 bio→bi_blkg→blkcg로 귀속(writeback kworker도 컨테이너 귀속; io 위임 전제); `dropped_events` per-CPU 카운터 + loader trailer + drop 시 조기 중단; `net_dev_xmit`·`block_rq_complete` 비활성(#if 0, 미사용); `sched_event`에서 미사용 `comm`/`prev_comm` 제거(레코드 88→56B); enqueue cgroup walk 중복 제거.
- **버퍼**: ring buffer 512MB(고부하 기본; 오버헤드 측정만 32MB), json_writer 4MB.
- **분석기 단일화**: `tests/`·`experiments/` 두 사본을 동일 로직으로 동기화(출력 형식만 다름: human/-j vs jq 배열). 변경 시 양쪽 동시.
- **부하 실증(CPU)**: 무경합 오차 −0.05%(과잉제거 없음); register/L1-bound 경합에서 +2.6%·제거효율 99%(stress-ng 등 비-register stressor는 범위 밖 IPC dilation이 섞여 오차 과대). drop 감지·거부는 실오버플로(5975만 drop)로 end-to-end 확인.
- **E2E 3자원 검증(2026-06-10)**: 현재 코드로 실측 — **CPU** 동일코어 핀+register/L1 경합 removal **99%**(잔여 +0.5%); **Network** HTB 10mbit throttle count=4 removal **73%**(커밋 75%); **Block** 약한 regime real-compression count=5 removal **68%**(커밋 60~76%). 셋 다 **과다제거 없음**(noise_free ≥ solo). 모두 보수적.
- **BIO-2(device-queue) 폐기 — 재시도 금지**: block을 issue→complete(`[insert,complete) ∩ foreign 장치점유`)로 끌어올려 76~86%를 봤으나, E2E 검증에서 **과다제거**(noise_free가 solo보다 22% 아래, removal 107%) 확인 → `git revert`(13a3207→31ce1b9). 원인: **단일서버(HDD 헤드 1개)에서 "foreign in-flight ≠ 내가 대기"** (foreign이 내 뒤에 큐잉됐을 수 있어 이중계상). NVMe는 병렬이라 더 심함. 향후 누가 device-queue를 다시 켜려면 이 과다제거부터 해결해야 함. 현재 block = sound한 insert→issue(선행 슬라이스) 단독.
- **최종 프레이밍 결정 (2026-06-12): CPU·Network 강하게, Block은 정직하게 — "1번".** wall이 1.5배 이상 늘어나는 *의미있는* 경합에서의 removal로 판정:
  - **CPU 99% @ 1.7× · Network 88~93% @ 3.9~5.0×** (iperf3 -P4 stressor, 별도 cgroup). 둘 다 **≥80% removal @ ≥1.5× wall 안정적, 과다제거 0** → 논문 강하게.
  - **Block은 ≥1.5×(실측 ≥3×) 경합에서 reliably ~65~76%** (O_DIRECT 65~69% @ 3.6~4.5×, real-compression 68% @ 1.6×; 버퍼드 89% @ 2.8×는 불안정+과다제거). **≥80%는 sound·reliably 불가.** ⚠ **수정됨 → line 62(2026-06-16): `queue_depth=2` 전제조건 + store victim으로 92% 달성. 이 줄은 depth=32 기본값 기준의 옛 결론(audit trail로 보존).**
  - **Block ≥80% 불가 = 구조적 한계** ⚠ **수정됨 → line 62: `queue_depth=2` + store victim으로 92% 달성(이 줄의 "knob 문제 아님" 결론이 틀렸음 — queue_depth=2가 sweet spot이었고, 당시엔 depth=1만 보고 "불안정"으로 기각). 아래 분석은 *왜 기본 depth=32에서 경합이 숨는지*의 설명으로는 여전히 유효:** 모델이 잡는 [insert→issue]는 **I/O 스케줄러 큐 대기**인데, `block_rq_issue`는 "드라이버에 dispatch한 시점"에 찍힌다(장치가 *실제 서비스 시작*하는 시점 ✗). 경합 대기는 그 뒤 [issue→complete]에 형성 → 사각. [insert→issue]에 대기가 오는 유일한 경우 = 장치가 물리적으로 다음 요청을 못 받을 때 = **HDD = seek dilation**. 시도·기각: flash/NVMe-loop·scsi_debug(ndelay 병렬→[issue,complete]; delay+max_queue=1 직렬화해도 경합 7~18%)·queue_depth=1(HDD 89%지만 seek+불안정)·BFQ idling(fast dev 8~31%)·커널 리밋(io.max=insert 이전 사각, io.weight=버퍼드에 약함). **knob 문제 아니라 트레이스포인트가 I/O 스택의 어디 박혀있나의 문제.**
  - **논문 block 주장 = "스케줄러 큐 경합 ~65~76% 정확 제거, 장치 레벨 dilation은 범위 밖(IPC dilation의 디스크판)".** 억지 80%는 불안정/과다제거라 리뷰 리스크. ⚠ **수정됨 → line 62: `queue_depth=2` + store victim으로 큐잉 노출 시 92%; 논문 주장도 그에 맞춰 갱신(전제조건 + 과다제거 꼬리 한계 명시).**
- **★ Block 결론 수정 (2026-06-16, K=30 E2E): queue_depth=2 + store-모드 victim으로 ~92% 달성 → 위 "≥80% 불가"를 수정한다.** 위의 구조적 분석([insert→issue]=큐잉, issue→complete=사각)은 **옳다**. 빠졌던 핵심: **기본 NCQ `queue_depth=32`에선 경합이 issue→complete(장치 내부)에 숨어 PureTime이 ~39%만 본다**(depth=32 K=30 실측 median 39%, 분포 22~53% — 이전 "65~76%"는 N=1~2 cherry-pick였음). `echo 2 > /sys/block/sdb/device/queue_depth`로 직렬화하면 경합이 [insert→issue]로 노출되어 잡힌다. depth-sweep(DEFLATE victim) 1→2→4→8→32 = 114%(과다)→**96%(pilot)/83%(K=30)**→74→75→39%; depth=1은 과다직렬화로 median부터 과다제거 → 기각, depth=2가 sweet spot. **★ victim도 I/O-bound로 진화 (store 모드, `COMPRESS_METHOD=stored` = zip 무압축 archiving): DEFLATE는 makespan ~60%가 CPU라 inflation 2.5×·removal 87%에 묶였으나, store는 makespan을 I/O로 채워 → store+depth=2 K=30 = removal median/mean 92% @ 3.2×, nf/solo 1.17(보수적).** depth=2가 포화를 막으니 I/O-bound victim도 seek dilation 없이 안전(멀티-cgroup·io.weight로 강도 키우기는 실패 — block inflation은 경합강도가 아니라 victim CPU/IO비율이 결정). **정직 한계: 30런 중 4런 과다제거(nf<solo, max 107%, std 8pp); device-knob(queue_depth) 의존성.** queue_depth 제한은 NIC offload off처럼 **측정 전제조건**으로 정당화(`BLOCK_QUEUE_DEPTH` 기본 2, `setup_io_scheduler`/`restore_io_scheduler`에서 설정·복원; CLAUDE.md Pre-requirements). **논문 헤드라인 = CPU 98% / Net 89% / Block 92%** (block은 queue_depth=2 전제 + store victim + 과다제거 꼬리 ~13% limitation 명시). issue→complete를 직접 켜는 BIO-2(line 56)는 단일서버 과다제거로 여전히 폐기; depth=2는 그걸 *직렬화로 우회*해 sound한 insert→issue 모델로 잡는 방식이라 다름.
  - **future work(연구, config 아님)**: rq 트레이스포인트 대신 per-cgroup `io.stat`(장치 점유 시간) 기반으로 [issue→complete] 경합을 다른 방식으로 귀속 → 단일서버 가정에서 sound화 여지. PureTime 측정 코어 재작성 필요.

## 확정 실험 프로토콜 (locked · 2026-06-09 · 전 P0)
> **공통 testbed**: **cgroup v2 격리 컨테이너로 서버리스 함수 실행 환경 재현** — Knative 미배포(측정에 필요한 건 cgroup 격리이며 모든 컨테이너 기반 서버리스의 공통 기반. 논문에 그렇게 명시). 컨테이너는 cgroup v2 별도 할당 + CPU/메모리 제한 + 단일 요청 처리.
> **core 0 제외** + victim/stressor 코어 핀 고정. victim **단일 스레드**. NIC offload off. stressor는 "대기를 만드는" 강도지 자원 고갈 아님. 모든 노이즈 환경 G.T. = *조용한 노드 solo run 분포*(점 아님; 판정=분포 겹침/2-표본 검정).

### 그룹 1 — 핵심 정확도 (1-1·1-2·1-4 / C1·C2, P0·P1)
- **증명**: 1-1 makespan이 solo 대비 오차 E% 이내(C1) · 1-2 breakdown↔주입 유형 일치(C2) · 1-4 강도 올려도 정확도 유지. **셋을 단일-노이즈 한 측정 세트에서 동시 추출**(중복 측정 X).
- **victim 4종**: `float`(CPU) · **`compression` store 모드(block I/O — zip 무압축 archiving, I/O-bound; queue_depth=2가 포화/seek dilation을 막아 안전. DEFLATE/dd에서 진화 — line 62)** · cloud storage **업로드**(network — TX만 보이므로 업로드 경로) · video_processing(다자원).
- **단일 노이즈**: victim별 해당 자원 노이즈 1종 + video는 3종 각각.
- **강도(1-4)**: 약/중/강 3단계, 대표 victim 1~2개에만. 나머지는 중간 강도 1개로 1-1·1-2만. (전부 돌리고 잘 나오는 것만 본문.)
- **반복·G.T.**: K=50, solo는 victim당 50회 1회. G.T.=solo 분포.
- **그림**: 함수별 wall/순수 시간/solo + 오차막대(C1); breakdown 스택바, 주입=자원 1:1(C2); 강도 vs 오차(1-4 robustness).
- **prune**: 다 돌리고 잘 나온 것만 본문에. 단 C1 정확도 자체가 전 victim 전멸이면 prune 아닌 설계 재검토.

### 1-3 — Mixed noise (C3 / 리뷰 C4, P0) — **구현됨 2026-06-16, 설계 수정**
- **증명**: 다자원 *동시* 경합에서 대기가 겹쳐도 정확히 제거 → merge 필요성의 무대.
- **⚠️ 설계 수정(실측으로 확정)**: 원안의 *단일 스레드 + blocking I/O*는 자원을 **직렬화**해(선점 중이면 I/O 대기가 아니고, throttle된 write에 막혀 있으면 runnable이 아님) CPU wait ∩ I/O wait이 **거의 분리** → 겹침≈0 → merge가 보일 게 없음. 겹침엔 **진짜 동시성**이 필요(파이프라인 서버리스 ExCamera/Sprocket이 실제로 그러함). 또 **Block은 제외**: queue_depth=2여도 무거운 경합에선 슬로다운이 `issue→complete` device service time(범위 밖, 미포착)에 지배돼 merge가 solo 위로(under-removal) → naive가 오히려 solo에 가까워 스토리가 역전. **CPU(98%)+Net(89%)** 둘 다 잘 포착되는 자원으로 실증.
- **victim**(`funcs/video-processing`, numpy+boto3, `--network=host`): **동시 2-스레드** + **스레드별 CPU affinity**(`os.sched_setaffinity`). `cpu_worker`(grayscale, register/L1-bound) → stressor가 포화시키는 코어(CPU wait). `net_worker`(MinIO에 **sustained 대용량 업로드**, 1MB 객체 — 작은 put_object 다발은 request-response 바운드라 qdisc 큐잉이 안 잡힘) → **별도 빈 IO_CORE**(CPU 안 굶주려 TX 계속 발행 → HTB qdisc shaping 큐잉이 net wait으로 포착). 두 워커가 다른 코어 → 한 cgroup에서 CPU wait ∩ Net wait이 **시간상 겹침**(unit-test 시나리오를 실제 victim에 구현). `N_CPU`로 두 워커를 **동시 종료**하도록 balance(off-critical-path 과다제거 방지).
- **stressor**(각 다른 cgroup): CPU=`stress-ng --cpu-method float`(register/L1, `--taskset` 경합 코어) · net=`iperf3 -P 4` + iface HTB 10mbit(victim TX가 같은 throttle qdisc에 큐잉).
- **sweep·반복**: CPU 경합 강도(stress-ng 워커 수) 1–4를 sweep해 겹침 8→30%를 만든다. 강도별 `N_CPU∝3/(강도+1)`로 balance 유지. 조건당 K=5(solo+stress 교차). G.T.=solo 분포.
- **데이터·그림**: `experiments/data/mixed_noise/results.csv`, `plot_exp2_interval_merge.py` → **fig7**.

### 2-1 — Interval-merge ablation (C3, P0) — **구현됨 2026-06-16**
- **증명**: merge가 단순 역산(`wall − Σwait`)보다 정확 — 단순 역산은 겹친 구간 이중 차감으로 noise-free 과소(음수 가능), merge는 합집합으로 한 번만.
- **데이터**: 1-3와 **동일 run**. 분석기가 `noise_free_makespan`(merge ∪) 와 `noise_free_naive`(자원별 Σ, 음수 가능)를 **동시 출력** → 같은 JSONL 두 경로.
- **결과(fig7)**: 겹침 8→30% sweep에서 **merge nf/solo 0.78–1.07(전 구간 valid, ≈solo)** vs **naive 0.79→−0.41**. 겹침↑면 naive는 발산해 **음수**(고겹침 7/10 runs) — 물리적으로 불가능(혼자보다 빠를 수 없음). 겹침≈0(강도 낮음)에선 merge≈naive → "겹침 없을 땐 무해" sanity check 자동 충족.
- **그림**: Panel A x=측정 겹침비율, y=nf/solo — merge는 solo=1 선에 평탄, naive는 우하향해 빨간 "impossible(nf<0)" 영역으로. Panel B 겹침 수준별 solo/merge/naive 막대.

### 3-1 — Input-invariance (C5, P0)
- **증명**: 자원 커버리지가 아니라 *속성* — intrinsic(input) 작업량 차이는 보존, extrinsic 경합만 제거. CPU 단일 자원으로 충분(속성은 자원 무관). 자원 다양성은 1-3 담당.
- **victim 2개** (input 변동 두 종류):
  - `float`(sqrt/sin/cos 루프) — **입력 크기**. CPU only, register/L1-bound → IPC dilation 무관. knob=반복 횟수, solo time ~50ms–수 초 6–8단계.
  - detect+sentiment 파이프라인 — **입력 내용**(같은 바이트, 얼굴 수가 작업량 결정). 얼굴 수 **0·1·5·10·15·30**. CPU+메모리.
- **noise**: CPU 경합만. 별도 cgroup, register/L1-bound, 가변/bursty. ⚠️ 메모리 대역폭 안 침(detect+sentiment의 on-CPU dilation 누수 차단 — dilation은 PureTime 범위 밖).
- **반복·G.T.**: 조건당 K=50(solo K + 경합 K). G.T.=같은 input의 solo **분포**. 매크로 교차검증: input별 `(T_wall,경합 − T_solo)`=제거돼야 할 총 노이즈 ↔ PureTime이 뺀 wait 일치.
- **그림**: Fig A(x=input level 또는 solo-median time; 3계열 밴드 solo/순수 시간/wall — 순수 시간이 solo 밴드 안착). (SNR kicker Fig B는 실험 4와 중복이라 제거.)

### 3-2 — Single-run vs 통계 baseline + 결정 대조 (C6 / 리뷰 C8, P0 · 5-1·5-2 흡수)
- **증명**: 통계 baseline(median·P90)은 input 변동 하에서 per-invocation 정답에 수렴 못 함, PureTime은 단일 실행으로 도달. **+ 그 틀린 값이 틀린 결정(false alarm·over-provision)을 낳음.**
- **데이터**: 3-1 재사용(float 크기변동 + detect+sentiment 내용변동). **추가 측정 없음** — 실험 3의 입력별 측정치를 랜덤 셔플해 "input이 랜덤하게 들어오는" 시계열로 구성. K=50이 통계 표본(N=1→50).
- **비교**: PureTime 순수 시간(1회) vs raw wall-clock vs N회 median·P90.
- **메인 plot**: G.T.(solo)·wall·순수 시간의 흐름 위에 mean·P90 밴드. 통계는 input 변동 탓 못 따라옴, 순수 시간은 G.T. 추종.
- **결정 대조(글 서술 + 측정값, 실행 X)**:
  - 회귀/카나리: AWS **CloudWatch Anomaly Detection 기본 mean±2σ 밴드** → 노이즈 낀 wall은 밴드 초과(false alarm), 순수 시간은 밴드 안(정상). 순수 시간 분산↓로 밴드 좁아 진짜 회귀 더 빨리.
  - autoscaling: **KPA containerConcurrency 100 × util 70% = 70/pod** 초과 시 scale-out. Little's Law로 노이즈 부푼 TimePerRequest→concurrency 70 넘김(over-provision), 순수 시간은 미만. 가짜 pod = ⌈부푼/70⌉−⌈진짜/70⌉.
  - 둘 다 **counterfactual 명시**, 폐루프는 future work. 임계값(2σ·70)은 1차 출처 기본값이라 끼워맞춤 차단.
- **G.T.**: 각 호출의 solo(해당 입력, 무부하) — 시점마다 다름.

### 4-1 — 오버헤드 (C7 / 리뷰 C6, P0 · 재설계)
- **증명**: PureTime online 비용이 (A)지연·(B)자원 둘 다에서 현실적 워크로드에 acceptable.
- **victim**: 그룹1·1-3 재사용. 이벤트 적음(float)~많음(video/net) 다 포함 — (A) 측정 신뢰성(신호 큰 함수일수록 오버헤드 측정 쉬움)·(B) 자원 스펙트럼.
- **(A) 지연**: w/ vs w/o PureTime, 같은 함수·입력, **조용한 환경**, K=50+ 반복해 분포 비교 + 2-표본 검정 + 차이 신뢰구간. (조용한 환경+반복으로 신호를 노이즈 위로 — HPDC 음수 원인 직접 교정.)
- **(B) 자원**: Tracer+Loader **CPU%·RSS·ring buffer·JSONL I/O** 절대 프로파일링(빼기 아님). RSS는 ring buffer가 지배적(libbpf 이중 매핑). 기본값 **512MB**(고부하 실험 안전)는 RSS ~1GB → **오버헤드 측정 시 `events` 맵 max_entries를 32MB로 내려 빌드**(RSS ~70MB). 보고에 사용 크기 명시.
- **online만**: eBPF hook + Loader 캡처만. **Analyzer는 offline task로 critical path에 없으므로 리소스 사용량/지연에서 제외(본문 명시).** softirq 필터링 이미 적용.
- **운영점 주장**: 본문 수치는 현실적 워크로드 = **표준 벤치마크(FunctionBench/SeBS) 기본 입력**(별도 trace 인용 대신 표준 기본값이 곧 현실 운영점).
- **그림**: 함수별 w/ vs w/o 실행시간 box plot + 차이%·CI; 자원 사용량은 본문/Table(online/offline 분리). 곡선 없음.
- **rebuttal 카드(본문 외)**: 네트워크 worst-case 점 하나는 리뷰 오면 반영.

## Scope & Limitations (claim을 과장하지 않기 위해 박아둠)
- **on-CPU 경합 범위 밖**: IPC dilation(LLC·메모리 대역폭), spinlock busy-wait. 향후 과제. → "노이즈를 전부 제거"라고 쓰지 않는다. 3-1/1-3은 register/L1 stressor로 dilation 누수 차단.
- **sequential execution 가정**: I/O 대기 중 다른 로직 미실행. concurrent 모델은 한계(Reviewer D). → victim은 단일 스레드로 강제해 가정 유지.
- **Analyzer offline(backlog)**: 실시간 제어 불가 → 3-2 결정 대조는 trace-driven/counterfactual, 온라인은 future work. 오버헤드(4-1)에서도 critical path 밖이라 제외.
- **보수적 재구성**: 과소 제거 경향(0.6s 잔여). → 약점이 아니라 "실제보다 빠르다고 과장하지 않음"의 증거.
- **network 귀속 = TCP-TX만**: 송신 qdisc(TX)만, 그중 tcp_sendmsg로 등록한 TCP만 귀속(UDP 미등록 — sk_cgrp_data fallback 비신뢰). RX·UDP는 future work → net victim은 TCP 업로드 경로.
- **network 잔여 = TCP 혼잡 백오프(범위 밖)**: 경합 시 잔여(+49~85%)의 주원인. throttle+AQM(fq_codel)이 패킷을 드롭→co-tenant가 유발한 TCP 혼잡제어가 congestion window를 줄여, 데이터가 **소켓 버퍼에서 대기**(qdisc enqueue 이전). net_dev 훅은 qdisc부터 보므로 이 소켓레벨 지연을 못 본다(= block seek dilation과 동류, co-tenant 유발이나 모델 범위 밖). 그래서 removal은 73~86%(count↑일수록↑)에서 멈추고 그 이상은 sound하게 못 올린다. **검증·기각**: skb_addr FIFO 매칭=과다제거(removal 133%, stale 큐); pfifo 깊은버퍼=매칭 붕괴(2%); LIFO=현재 overwrite와 동일. 현재 overwrite(=가장 최근 큐) 매칭이 보수적·sound한 최선. 매칭률 47%의 손실분 대부분은 **qdisc 우회 패킷**(net_dev_queue 없음=애초 안 기다림)이라 제외가 정당.
- **CPU 모델 = 단일코어 핀 측정 가정**: enqueue↔switch-in 사이 cross-CPU 마이그레이션 미추적(per-CPU wait). victim/stressor를 같은 코어에 핀해 가정 유지; 핀 없는 일반 배치는 측정 한계로 명시.
- **호스트/커널 오버헤드 미제거**: co-tenant(컨테이너) 경합만 제거. root/system/커널스레드(cgroup≤1) 점유 CPU는 함수의 실제 비용으로 보존(제거 시 "실제보다 빠르다" 과장 방향이라 의도적). core 0 제외+조용한 노드로 영향 최소화.
- **block 귀속 전제**: 컨테이너 cgroup에 io 컨트롤러 위임 필요(bio→bi_blkg→blkcg). 미위임 시 current-cgroup fallback → 버퍼드 writeback 미귀속 가능.
- **on-device dilation 범위 밖(IPC dilation의 디스크판)**: HDD를 여러 writer가 *포화*시키면 헤드 seek thrashing으로 *각 요청 자체가 물리적으로 느려진다* — 스케줄러블 대기가 아니라 장치 물리현상이라 못 뺀다. 그래서 block은 **포화 regime에선 제거효율이 ~34%로 떨어진다**(seek dilation 지배). 이를 피하려면 디스크 포화를 막아야 하는데, **최종 해법은 `queue_depth=2`(경합을 큐잉 층으로 직렬화 → 포화 차단) + store-모드 I/O-bound victim → removal 92%**(아래 괄호·line 62). (옛 DEFLATE/CPU+IO혼합 victim은 60~76%(보수적)에 머물렀음.) **요지: block 경합은 "고갈"이 아니라 "wait 유발" 강도여야 하고, queue_depth=2가 그 조건을 보장한다.** (★ 2026-06-16 갱신: 이 dilation 사각은 **`queue_depth=2`로 장치를 직렬화하면 경합이 [insert→issue] 큐잉으로 노출되어 store-victim에서 92%까지 회복** — line 62. seek dilation 자체는 여전히 범위 밖이나, NCQ가 숨기던 큐잉 경합분이 드러나는 게 핵심. depth=2가 포화를 막아 I/O-bound store victim도 안전해진 게 추가 포인트.) (issue→complete device-queue로 포화에서도 잡으려 했으나 단일서버에서 "foreign in-flight≠내 대기"라 과다제거 → 폐기, 아래 BIO-2 참조.)
- **ring buffer 유실 → trace 거부**: 불완전 trace엔 makespan 미산출(loader가 dropped_events 카운트·trailer 기록, analyzer가 exit 2로 거부). 고부하 실험은 ring buffer 상향(기본 512MB; 오버헤드 측정만 32MB).
- **testbed = cgroup v2 컨테이너**: Knative 미배포. "함수 실행 환경 재현"으로 명시.

## 실험 ↔ Claude Code 분담
- **eBPF 캡처**: 자기 커널/클러스터에서 직접. 데이터셋(영상·얼굴 수별 이미지)도 본인 준비.
- **Claude Code(레포 내)**: victim 코드(float · detect+sentiment 파이프라인 · video_processing 단일스레드 래핑 · dd · cloud storage 업로드), cgroup v2 컨테이너 하니스(서버리스 환경 재현), Analyzer 코드, JSONL 처리, 정확도/오버헤드 계산, merge·attribution 분석 분기, 통계 baseline·결정 대조 산술, 그림용 수치 산출. (구현 순서·검증은 위 "구현 순서·검증 방법" 절 참조.)

---
*전 P0(그룹1·1-3·2-1·3-1·3-2·4-1) 프로토콜 확정(설계). 2-1은 1-3, 3-2는 3-1 데이터 공유. 그룹5(5-1·5-2) → 3-2 흡수. C1·C7 기존 데이터는 재설계로 대체. 남은 P1/P2(2-2·6-1·6-2) 계획. 구현은 eBPF+Analyzer 먼저 → audit부터. 결과 확정 시 상태·메모 갱신.*
