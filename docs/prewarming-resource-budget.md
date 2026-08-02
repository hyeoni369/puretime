# Pre-warming + 함수 실행 = 리소스 100%를 넘는가 — 자원 예산 점검

조사 질문: pre-warming의 각 task가 **어떤 리소스를 주로 쓰는지**, 함수 실행이 **어떤 리소스를 주로 쓰는지**, 그 리소스들이 서버리스 풀에서 **100%로 도는지 여유가 있는지**, 그래서 **둘이 동시에 돌 때 100%를 넘는지**.

## 0. 근거 기준과 검증 한계

논문(peer-reviewed 또는 arXiv preprint)에 보고된 값만 사용. 논문 진술이 아닌 것은 `▶ 해석`으로 표시.
**⚠** egress 정책이 usenix.org / arxiv.org / dl.acm.org 접근을 차단하여 **원문 PDF를 직접 열지 못했다.** 근거는 논문 PDF 색인 스니펫이다. `[preprint]` = peer-review 미확인. **인용 전 원문 재대조 필수.**

---

## 1. 답 먼저

**"넘는가"의 답은 자원마다 다르고, 가장 먼저 100%에 닿는 것은 CPU가 아니다.**

| 자원 | 풀의 평상시 상태 | 동시 실행 시 100% 넘는가 | 판정 근거 |
|---|---|---|---|
| **CPU** | **여유 있음** | **안 넘는다 (평상시)** | 초당 1750–2500 cold start를 돌려도 CPU가 아니라 **커널 락**에서 먼저 포화; 그 시점 제어평면 CPU는 **55%**(Dirigent) |
| **커널 락 / 직렬화** | — | **여기가 가장 먼저 100%를 친다** | containerd 기준 **1750 cold start/s에서 포화**, 원인이 sandbox 생성·네트워크 인터페이스 설정·iptables의 **커널 락 경합**(Dirigent) |
| **메모리 (할당 슬롯)** | **이미 포화에 가까움** | **넘는다** | 시스템이 메모리의 **70–87%를 낭비**(할당했으나 미사용); 밀도 한계가 메모리(1편) → 새 인스턴스는 기존 warm 인스턴스를 **축출**해야 들어간다 |
| **메모리 (실사용량)** | 여유 있음 (40–60%) | 안 넘는다 | 하이퍼스케일러 메모리 사용률 **40–60%**대 |
| **디스크 I/O** | **데이터 없음** | **판정 불가** | §5 참조 — pre-warming은 I/O 중심인데 풀의 I/O 가동률을 보고한 논문을 찾지 못함 |

### ⚠ 오해 방지 — "cold start의 병목 = 커널 락"은 **동시성이 높을 때만** 참이다

위 표의 "커널 락이 가장 먼저 100%를 친다"는 **처리율(초당 몇 개를 띄울 수 있나)**에 대한 진술이지, **단일 cold start의 지연 구성**에 대한 진술이 아니다. 둘은 정반대에 가깝다.

| | 단일 / 저동시성 기동 | 고동시성 기동 |
|---|---|---|
| 커널 연산 비중 | namespace 생성 **8–10ms = 전체의 1.5% 미만** | `clone()` 하나가 **1.45ms → 418ms** (호스트 커널 락 경합) |
| 지연을 지배하는 것 | **스토리지·런타임 연산 550–1850ms** (이미지 pull, page fault, 런타임 초기화) | **커널 락 대기** |
| 근거 | Decomposing Docker Startup `[preprint]` | Fork in the Road OSDI'25 |

추가 근거: 동시 실행에서는 **서버에 코어가 충분한데도** 총 실행시간이 급증하며, 그 시간의 **90% 이상이 startup**에 쓰인다(Agile Cold Starts, HotCloud'19). AFaaS는 직렬 실행 대비 **24× 동시성**에서 cold start 지연과 변동이 크게 증가한다고 보고한다.

▶ **해석.** 따라서 정확한 진술은 *"cold start의 병목은 커널 락이다"*가 아니라 **"단일 기동의 지연은 I/O와 런타임 초기화가 지배하고, 동시 기동의 처리율과 지연은 커널 락이 지배한다"**이다. 마찬가지로 *"pre-warming은 계산보다 락 대기에 시간을 더 쓴다"*도 **동시 기동일 때만** 참이며, 한 개씩 여유롭게 띄우면 시간의 대부분은 **디스크·네트워크 I/O**이고 그 다음이 **런타임 초기화(진짜 CPU)**다(§2 T2·T4·T5).

▶ **핵심 해석.** 의뢰가 세운 프레임("동시에 돌면 100% 넘나?")으로 계산하면, **CPU 축에서는 안 넘는다**는 답이 나온다. CPU는 남고(§4), CPU가 포화하기 훨씬 전에 **커널 락**이 먼저 막히기 때문이다(Dirigent가 이걸 직접 측정했다). 그런데 그 대신 **메모리 할당 슬롯 축에서는 이미 넘고 있다** — 새 인스턴스를 넣으려면 기존 warm 인스턴스를 밀어내야 하는 상태다. 즉 "pre-warming이 CPU를 뺏어 함수를 못 돌게 한다"는 가설은 기각되고, "**pre-warming이 메모리 슬롯을 뺏어 다른 함수를 cold start로 밀어낸다**"가 실제 경합 경로다.

---

## 2. Pre-warming task별 주 사용 리소스

| Task | 주 사용 리소스 | 근거 수치 | 출처 |
|---|---|---|---|
| T1 스케줄링/배치 결정 | 제어평면 CPU + 네트워크 RPC | Firecracker 2500 starts/s 피크에서도 제어평면 CPU **55%** | Dirigent `[preprint]` |
| T2 이미지·코드·의존성 확보 | **네트워크 + 디스크 I/O** | 커스텀 이미지 **>1.3GB**, 원격 pull 시 cold start 수 분 | FaaSNet ATC'21 |
| T3 커널 격리객체(namespace/cgroup/mount) | **커널 락 (직렬화)** — CPU 시간은 거의 안 씀 | namespace 생성이 startup의 **8–10ms (<1.5%)**; cgroup 할당 **100–300µs** | Decomposing Docker Startup `[preprint]` |
| T4 샌드박스 기동 / 스냅샷 복원 | **디스크 I/O (page fault)** | 호출당 **수천 page fault**, 비연속 읽기 지배 | REAP ASPLOS'21 |
| T5 언어 런타임 초기화 | **CPU (진짜 CPU-bound)** | gVisor 기준 **Java 부팅이 e2e의 34–88%**; JVM은 class loading·JIT로 startup 중 CPU 상승 | Catalyzer ASPLOS'20 / UCC'25 |
| T6 유저 코드 초기화 | CPU + I/O | 인기 Python 라이브러리 import만으로 **~100ms** | SOCK ATC'18 |

**요약:** pre-warming의 리소스 프로파일은 **네트워크·디스크 I/O가 부피, 커널 락이 병목, CPU는 T5/T6에만 집중**이다. T3는 시간 비중이 1.5% 미만이라 **CPU 소비자로 볼 수 없고 락 소비자로 봐야 한다.**

---

## 3. 함수 실행의 주 사용 리소스

| 특징 | 수치 | 출처 |
|---|---|---|
| 실행이 짧다 | **50%가 1초 미만** | Shahrad ATC'20 |
| 할당된 CPU를 다 못 쓴다 | 과금 vCPU가 실제 사용의 **1.02–3.99배** | Demystifying Serverless Costs `[preprint]` |
| 할당된 메모리를 더 못 쓴다 | 과금 메모리가 실사용의 **1.95–5.49배** | 〃 |
| **짧은 버스트는 CPU 쿼터를 우회한다** | 20ms period/10ms quota(=0.5 vCPU)에서 10ms 작업은 **제한과 무관하게 순간 CPU 100% 점유 가능** | 〃 |
| 밀집 배치 시 컨텍스트 스위치가 문제 | 조밀 워크로드에서 컨텍스트 스위치 오버헤드가 **노드 성능을 심각하게 저하**시킬 수 있음 | Densely Packed Linux Clusters `[preprint]` |

**요약:** 함수 실행은 **CPU를 주로 쓰되 할당량의 일부만** 쓰고, **메모리는 할당량 대비 훨씬 덜** 쓴다. ▶ 해석: 함수 실행 쪽이 CPU를 꽉 채우지 않기 때문에 CPU 축에 헤드룸이 생긴다.

---

## 4. 서버리스 풀은 100%로 도는가 — 자원별 가동률

| 자원 | 보고된 가동률 | 출처 |
|---|---|---|
| CPU (일반 FaaS) | Meta XFaaS가 **일 평균 66%**를 달성했고, 논문은 이것이 **일반 FaaS 플랫폼의 몇 배**일 수 있다고 서술(단, 논문 스스로 "anecdotal knowledge 기반"이라 명시) | XFaaS, SOSP'23 |
| CPU 낭비분 | 현행 시스템이 **CPU의 9–20%를 낭비** | Melding the Serverless Control Plane `[preprint]` |
| 메모리 낭비분 | 현행 시스템이 **메모리의 70–87%를 낭비** | 〃 |
| 메모리 사용률 | 하이퍼스케일러 메모리 사용률 **40–60%**대, 클라우드 메모리의 최대 50%가 저활용 | 메모리 dedup/disaggregation 문헌 |
| 메모리 과할당 | 스케일링 정책이 실사용 대비 **2–10× 할당** | High Cost of Keeping Warm `[preprint]` |
| 전반 | Alicloud·Huawei 트레이스에서 **CPU·GPU 모두 심각하게 저활용** | Jiagu ATC'24 |

**요약:** **CPU는 여유가 있다.** 메모리는 *실사용률*로는 여유가 있으나 *할당 기준*으로는 이미 낭비가 70–87%에 달할 만큼 꽉 차 있다 — 이 둘의 차이가 이 문제의 핵심이다.

---

## 5. 종합 — 동시에 돌면 100%를 넘는가

### 5.1 CPU 축: 안 넘는다 (그리고 그걸 직접 잰 논문이 있다)

가장 직접적인 증거는 Dirigent다: **containerd로 초당 1750개, Firecracker microVM으로 초당 2500개의 cold start**를 돌렸을 때 —
- 포화 원인은 CPU가 아니라 **sandbox 생성·네트워크 인터페이스 설정·iptables 규칙 갱신에서의 커널 락 경합**이었고,
- 그 피크에서도 **제어평면 CPU 사용률은 55%**에 그쳤다.

▶ **해석.** 이는 "pre-warming을 아주 공격적으로 돌려도 CPU는 100%에 닿기 전에 다른 것(커널 락)이 먼저 막는다"는 뜻이다. 함수 실행 쪽도 할당 CPU의 일부만 쓰고(§3) 풀 자체가 저활용이므로(§4), **CPU 합계가 100%를 넘는 시나리오는 평상시엔 성립하지 않는다.**

**단, 두 가지 예외:**
1. **T5(런타임 초기화)는 진짜 CPU를 쓴다** — Java 부팅이 e2e의 34–88%(Catalyzer). 무거운 런타임을 대량으로 동시에 예열하면 이 구간은 실제 CPU 경합이다. 실제로 **startup 피크 수요를 감당하려 CPU를 과할당하는 것이 흔한 전략**이라고 보고된다(UCC'25).
2. **cgroup CPU 쿼터가 짧은 버스트를 못 막는다**(§3) — 그래서 "limit을 걸었으니 안전"이라는 방어는 성립하지 않는다.

### 5.2 커널 락 축: 여기가 먼저 100%를 친다

1750 cold start/s에서의 포화(Dirigent), `clone()` 1.45ms→418ms 악화(OSDI'25), Kata 100개 동시 기동에서의 rootfs·cgroup 저하(ATC'22)가 모두 같은 것을 가리킨다. ▶ 해석: **pre-warming의 실질적 상한선은 CPU 코어 수가 아니라 초당 기동 수다.**

### 5.3 메모리 축: 이미 넘고 있다

- 시스템이 메모리의 **70–87%를 낭비**하고(할당했으나 미사용), 스케일링 정책이 실사용 대비 **2–10× 할당**한다.
- 밀도 한계가 메모리다(384GB 노드에 2500개, 1편).
- 그래서 새 인스턴스를 넣으려면 **기존 warm 인스턴스를 축출**해야 하고, warm pool이 한 테넌트로 점거되면 **다른 테넌트 컨테이너가 축출되어 이후 요청이 전부 cold start**가 된다(FaasCamp `[preprint]`).

▶ **해석.** 여기가 "pre-warming이 다른 함수의 실행을 막는" 유일하게 직접적인 경로다. 그리고 이건 **사용률 100%가 아니라 할당 100%** 문제다 — 실사용 메모리는 40–60%인데도 할당 슬롯은 꽉 차 있다.

### 5.4 디스크 I/O 축: 판정 불가 (공백)

pre-warming은 I/O 중심 작업이다 — 이미지 pull 1.3GB 초과(T2), 호출당 수천 page fault(T4). 그런데 **서버리스 풀의 디스크 I/O 가동률(대역폭·IOPS·큐 깊이)을 보고한 논문을 이번 조사에서 찾지 못했다.** CPU·메모리와 달리 이 축은 "여유가 있는지" 자체를 논문 근거로 말할 수 없다.

### 5.5 상충하는 두 측정 (숨기지 않고 기록)

- **High Cost of Keeping Warm** `[preprint]`: 샌드박스 기동/철거가 **함수 실행 CPU 사이클의 10–40%**에 해당.
- **Melding** `[preprint]`: 인스턴스 생성 요청으로 제어평면을 압박하는 산발적 트래픽은 **클러스터 자원의 2% 미만**만 사용.

두 값은 대상 시스템과 정의(전자는 Knative 기반 시스템의 worker node CPU 사이클 비율, 후자는 프로덕션 트레이스의 트래픽 계층별 자원 점유율)가 달라 직접 비교할 수 없다. ▶ 해석: **churn의 CPU 비용이 "함수 실행 대비 10–40%"인지 "클러스터 자원의 2% 미만"인지가 문헌상 정리되지 않았다.** 이 폭이 §5.1 결론의 가장 큰 불확실성이며, 둘 다 preprint다.

---

## 6. 한 줄 결론

**CPU 축에서는 안 넘는다** — 풀 CPU가 저활용이고, 초당 수천 건의 기동을 돌려도 CPU가 아니라 커널 락이 먼저 포화하며 그때조차 제어평면 CPU는 55%다. **넘는 것은 메모리 할당 슬롯과 커널 락 처리율이다.** 따라서 pre-warming의 안전성은 "CPU를 얼마나 쓰나"가 아니라 **"초당 몇 개를 띄우나(락)"와 "메모리 슬롯을 누구에게서 뺏나(축출)"**로 관리해야 한다.

**아직 답할 수 없는 것:** 디스크 I/O 축의 여유(§5.4)와 churn CPU 비용의 실제 크기(§5.5).

---

## 7. 참고문헌 (앞 두 편에 없던 것)

**Peer-reviewed**
1. A. Sahraei et al. **"XFaaS: Hyperscale and Low Cost Serverless Functions at Meta."** ACM SOSP 2023. https://dl.acm.org/doi/10.1145/3600006.3613155
2. **"A Self-Adaptive Framework for Predictive CPU Resource Allocation During Container Startup in Kubernetes."** IEEE/ACM UCC 2025. https://dl.acm.org/doi/10.1145/3773274.3774262

**Preprint (peer-review 미확인)**
3. **"Dirigent: Lightweight Serverless Orchestration."** arXiv:2404.16393
4. **"Melding the Serverless Control Plane with the Conventional Cluster Manager for Speed and Resource Efficiency."** arXiv:2505.24551

*(앞 두 편에서 이미 인용한 문헌 — Shahrad ATC'20, REAP ASPLOS'21, SOCK ATC'18, RunD ATC'22, Fork in the Road OSDI'25, FaaSNet ATC'21, Catalyzer ASPLOS'20, Jiagu ATC'24, Decomposing Docker Startup, Demystifying Serverless Costs, High Cost of Keeping Warm, FaasCamp, Densely Packed Linux Clusters — 는 `docs/prewarming-evidence.md` 및 `docs/prewarming-task-anatomy.md` §7 참조.)*
