# PureTime 구현 핸드오프 (논문 Writing용)

> 이 문서는 **구현 사실과 검증 결과만** 담는다. 논문 프레이밍/스토리는 초안(PDF)을 따른다.
> 모든 수치는 현 코드(`audit` 브랜치)로 실측한 값이며 보수적(과다제거 없음)이다.

---

## 1. 시스템 아키텍처 (3-stage 파이프라인)

```
커널 eBPF (Tracer) --512MB ring buffer--> 유저스페이스 Loader (JSONL) --파일--> Python Analyzer
   src/puretime.bpf.c                       src/puretime.c                    tests/noise_free_makespan.py
```

- **단일 호출(single invocation)에서 완결**. 통계 표본·reference run 불필요(reference-free).
- 세 단계는 `src/puretime.h`의 바이너리 구조체 계약으로 연결(공통 `event_header`: timestamp_ns, cgroup_id, cpu, event_type).

---

## 2. Tracer (커널 eBPF) — 무엇을 잡는가

**8개 active eBPF 프로그램**이 이진 이벤트를 512MB ring buffer로 발행(커널에서 JSON 안 만듦; reserve 실패 시 per-CPU `dropped_events` 증가).

| 훅 | 발행 이벤트 | cgroup 귀속 |
|---|---|---|
| `fentry/enqueue_task`, `tp_btf/sched_switch` | sched_enqueue, sched_switch | task→cgroups→dfl_cgrp→kn→id |
| `tp_btf/net_dev_queue`, `net_dev_start_xmit` | net_dev_queue, net_dev_start_xmit | tracked_sockets 조회 (tcp_sendmsg가 등록) |
| `tp_btf/block_rq_insert`, `block_rq_issue` | block_rq_insert, block_rq_issue | blkcg (rq→bio→bi_blkg→blkcg→css.cgroup), 실패 시 current-cgroup |
| `tp_btf/softirq_entry`, `softirq_exit` | softirq_entry, softirq_exit | current cgroup |
| `fentry/tcp_sendmsg`, `tcp_close` | (이벤트 없음) socket→cgroup 등록/삭제 | 프로세스 컨텍스트 |

- **네트워크 귀속 트릭**: softirq 컨텍스트에선 소켓 cgroup이 root로 보임 → `tcp_sendmsg`(프로세스 컨텍스트)에서 `socket→cgroup_id`를 hash map에 미리 등록, net 훅이 이를 조회. **TCP-TX 전용**(UDP 미등록).
- **블록 귀속**: blkcg 경로로 writeback kworker가 제출한 버퍼드 쓰기도 컨테이너에 귀속(io 컨트롤러 위임 전제).
- 필터: cgroup_id ≤ 1(root/idle) 제외; softirq는 NET_TX/NET_RX/BLOCK vector만.
- `net_dev_xmit`, `block_rq_complete`는 코드에 있으나 **비활성(`#if 0`)** — 분석기가 안 씀(이벤트 볼륨 절감).
- ring buffer 기본 512MB(고부하 drop 방지). **오버헤드 측정 실험에선 32MB로 낮춰 빌드**(RSS가 측정 대상이므로).

---

## 3. Loader (유저스페이스, libbpf)

- skeleton open/load/attach → `ring_buffer__poll(100ms)` → 각 이벤트를 JSONL 한 줄로 직렬화(`json_writer`, **4MB 버퍼**로 write() syscall 분할상환).
- 종료 시 per-CPU `dropped_events` 합산 → `{"event":"trace_summary","dropped_events":N}` 트레일러 기록. drop 발생 시 조기 종료 + 경고.

---

## 4. Analyzer — 측정 모델 (novelty 핵심)

**2-pass**: (1) cgroup 감지(이벤트 수·시간 범위), (2) 전체 이벤트를 **timestamp 정렬**(멀티-CPU 순서 보정) 후 처리.

**자원별 동일 원리**: *start 이벤트*를 key로 *complete 이벤트*에 매칭 → 그 사이 **다른 cgroup이 먼저 서비스된 구간**을 wait으로 귀속.

| 자원 | start → complete | key | wait 구간 |
|---|---|---|---|
| CPU | sched_enqueue → sched_switch | tid | 내 enqueue 이후 같은 CPU에 다른 cgroup이 switch-in한 `[other, my_switch)` |
| Network | net_dev_queue → net_dev_start_xmit | skb_addr | 내 queue 이후 다른 cgroup 패킷이 dequeue된 `[other, my_dequeue)` |
| Block | block_rq_insert → block_rq_issue | request_addr | 내 insert 이후 다른 cgroup 요청이 issue된 `[other, my_issue)` |
| Softirq | softirq_entry → softirq_exit (CPU별) | cpu | 구간 duration을 cgroup별 이벤트 수 비율로 self/other 분배 |

- **interval merge (핵심)**: 모든 wait 구간을 `portion` 집합으로 저장 → 자원 간/내 **겹침을 union으로 자동 병합**(중복 차감 방지).
- **CPU·Block 선행 슬라이스**: start 시점에 이미 다른 cgroup이 자원을 쥐고 있었으면 `[my_start, 다음 이벤트)`도 wait으로 계상(과소계상 교정).
- wait union을 cgroup 생존구간 `[first_ts, last_ts]`로 **clamp**(범위 밖 차감 방지).
- **최종**: `noise_free_makespan = (last_ts − first_ts) − interval_sum((cpu ∪ net ∪ bio ∪ softirq_other) & span)`
  - `softirq_self`는 계산·보고하되 차감 안 함(other만 차감).
- **interval-merge ablation(C3)**: union 없이 자원별 wait을 단순 합산한 `noise_free_naive`도 출력(음수 가능) → merge 효과 비교용.

**런타임 invariant (assert로 강제)**: noise_free ≤ wall_clock · 모든 wait ≥ 0 · merge union ≤ Σ(구간) AND ≤ wall_clock · drop > 0이면 trace 거부(exit 2). → **구조적으로 과다제거 불가**(wait ⊆ [start,complete) ⊆ makespan).

---

## 5. 검증 결과 (현 코드 실측, 보수적)

> 판정 기준: **wall이 ≥1.5배 늘어나는 의미있는 경합**에서의 removal(= 제거된 노이즈 / 전체 노이즈). solo run = G.T. 셋 다 noise_free ≥ solo(과다제거 없음).

| 자원 | removal | wall 배율 | stressor | 잔여 |
|---|---|---|---|---|
| **CPU** | **99%** | 1.7× | register/L1-bound 루프, 동일코어 핀 | +0.5% |
| **Network** | **88~93%** | 3.9~5.0× | iperf3 `-c -P` (TCP), HTB 10mbit throttle | +49~85% |
| **Block** | **65~76%** | ≥3× | fsync 쓰기(compression/dd), BFQ | +19~85% |

- **CPU**: 무경합 baseline 오차 −0.05%. register/L1 stressor에서 +2.6%/99%. (cache/membw 오염 stressor면 +8.3%로 오차 부풀음 — IPC dilation 누수, 범위 밖.)
- **Network**: 강도(iperf3 `-P` flow 수)에 비례해 removal 상승(2 flow ~50% → 8 flow ~86%). 잔여는 TCP 혼잡 백오프(범위 밖).
- **Block**: 스케줄러 큐 경합만 제거. 잔여는 장치 레벨 dilation(범위 밖).
- 드롭 감지·거부: 실제 ring buffer 오버플로(5975만 drop)로 end-to-end 확인.

**오버헤드**: online(eBPF 훅 + Loader 캡처)만 해당. Analyzer는 offline(critical path 밖). 측정 시 ring buffer 32MB로 빌드(RSS ~70MB).

---

## 6. Scope & Limitations (over-claim 방지 — 논문에 반드시 명시)

- **co-tenant(컨테이너) 경합만 제거.** host/kernel/system(cgroup ≤ 1) 점유는 함수의 실제 비용으로 **보존**(제거 안 함).
- **on-CPU IPC dilation**(LLC·메모리 대역폭 경합으로 victim 자기 명령어가 느려짐) = **범위 밖.** → CPU stressor는 register/L1-bound로 유지.
- **Network = TCP-TX 전용**(tcp_sendmsg 등록 TCP 송신만; UDP·RX 미지원). **TCP 혼잡 백오프**(소켓 버퍼 대기, qdisc 이전)는 net_dev 훅 사각 = **범위 밖.**
- **Block**: io 컨트롤러를 컨테이너 cgroup에 위임해야 blkcg 귀속(미위임 시 current-cgroup fallback). **장치 레벨 dilation**(HDD seek, NCQ 재정렬) = **범위 밖.**
  - 구조적 이유: `block_rq_issue`는 "드라이버 dispatch" 시점에 찍혀 모델이 [insert→issue](스케줄러 큐 대기)만 봄. 경합 대기 상당부분은 그 뒤 [issue→complete](장치)에 형성되어 사각 → block removal이 ~65~76%에서 멈춤. (다양한 디바이스/스케줄러/커널-리밋 설정 실측으로 확정. 트레이스포인트 위치 한계라 config로 못 품. future work: per-cgroup `io.stat` 기반 재측정.)
- **CPU wait 모델 = 단일코어 핀 가정**(cross-CPU 마이그레이션 미추적).
- **sequential execution 가정**: victim은 단일 스레드(I/O 대기 중 다른 로직 미실행).
- **"노이즈를 전부 제거"라고 쓰지 말 것.** 각 자원의 범위-밖 dilation은 잔여로 남으며, 이는 의도적(보수적, "실제보다 빠르다고 과장 안 함").

---

## 7. 실험 셋업 (재현용)

- **공통**: cgroup v2 격리 컨테이너로 서버리스 함수 실행 재현(Knative 미배포). core 0 제외 + victim/stressor 코어 핀. victim 단일 스레드. solo run 분포 = G.T. K=50 반복. 판정 = 분포 겹침/2-표본 검정.
- **victim**: CPU=`float`(sqrt/sin/cos 루프) · Network=cloud storage 업로드(MinIO, TCP) · **Block=`compression`**(write+fsync→압축; CPU+block 혼합이라 디스크 경합이 *wait-유발* 강도에 머묾. 순수 `dd`는 디스크 *포화*→seek dilation(범위 밖)으로 부적합) · 다자원=video_processing.
- **stressor(각 별도 cgroup)**: CPU=register/L1 루프 · Network=`iperf3 -c`(TCP, level≥2 cgroup, 강도=`-P` flow 수, HTB 10mbit+fq_codel throttle, iperf3 서버 필요) · Block=fsync 쓰기(같은 디바이스, BFQ).
- **선결 조건**: NIC offload off(`ethtool -K`); 블록 스케줄러 `[none]` 금지(mq-deadline/bfq); 네트워크는 MinIO + `uploads` 버킷.
- **실행**: `make build` → `sudo src/puretime -v -t N` → `python3 tests/noise_free_makespan.py <trace> -j`. 실험 하니스: `experiments/exp_accuracy_by_type.sh`(CPU/Net/Block accuracy sweep).

---

## 8. 코드 위치 빠른 참조
- Tracer: `src/puretime.bpf.c` · Loader: `src/puretime.c` · 공유 헤더: `src/puretime.h`
- Analyzer(canonical): `tests/noise_free_makespan.py` (출력 human/-j); 실험용 동일 사본: `experiments/noise_free_makespan.py`(jq JSON)
- 단위테스트: `tests/test_noise_free_makespan.py` (9개; span-clamp·drop거부·in-span wait·선행슬라이스·merge-vs-naive ablation)
- victim: `funcs/` · 실험 하니스: `experiments/`
