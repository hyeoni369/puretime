# Pre-warming의 작업 분해와 "함수 실행을 막는가" 판정 — 논문 근거 조사 (2편)

1편(`docs/prewarming-evidence.md`)의 후속. 이번 조사 질문:
1. **Pre-warming은 어떤 task들로 이루어져 있는가**, 각 task의 자원 성격은?
2. **함수 실행**의 자원 특징은?
3. 보통 서버리스 컴퓨팅 풀의 **CPU / 메모리 상태**는?
4. 위 셋을 근거로 — pre-warming은 **충분히 좋은 솔루션인가**, 아니면 **함수 실행을 막으면서 진행되는 솔루션인가**?

## 0. 근거 기준과 검증 한계 (1편과 동일, 반드시 유지)

논문(peer-reviewed 또는 arXiv preprint)에 보고된 내용만 사용했다. 논문 진술이 아닌 문장은 `▶ 해석`으로 표시했다.

**⚠** egress 정책이 usenix.org / arxiv.org / dl.acm.org 접근을 차단(CONNECT 403)하여 **원문 PDF를 직접 열지 못했다.** 근거는 각 논문 PDF를 색인한 검색 스니펫이다. 등급: `A` = 해당 논문에 직접 귀속 / `B` = 2차 인용이라 원문 재확인 필요. `[preprint]` = peer-review 미확인. **인용 전 원문 재대조 필수.**

---

## 1. 결론 먼저

**판정: pre-warming은 "CPU를 빼앗아 함수 실행을 막는" 솔루션이 아니다. 그러나 "충분히 좋은 솔루션"도 조건부다 — 실제 병목은 CPU가 아니라 메모리 용량과 동시성 제어에 있다.**

세 축으로 나뉜다.

| 축 | 판정 | 핵심 근거 |
|---|---|---|
| **CPU (평상시)** | **막지 않는다** | 프로덕션 풀의 CPU가 심각하게 저활용(Jiagu, ATC'24) · idle warm 인스턴스는 CPU/전력 ≈ 0(1편 #25) · 커널 셋업 연산은 startup 시간의 **<1.5%**(preprint) |
| **CPU (버스트 시)** | **막을 수 있다** | 샌드박스 기동/철거가 **함수 실행 CPU 사이클의 10–40%**(preprint) · `clone()` 1.45ms→418ms(OSDI'25) · **cgroup CPU 쿼터가 짧은 버스트를 못 막는다**(preprint) |
| **메모리** | **막는다 (진짜 위험)** | 밀도 한계가 메모리(1편 #22·#23) · 스케일링 정책이 실사용 대비 **2–10× 과할당**(preprint) · **warm pool 점거 → 타 테넌트 전량 축출 → 이후 요청 전부 cold start**(preprint) |

▶ **해석.** 의뢰의 원래 걱정("CPU 잡아먹어서 다른 함수가 늦어진다")은 **평상시엔 근거가 약하고, 버스트에서만 성립하며, 진짜 위험은 다른 곳(메모리 축출)에 있다.** 그리고 §2가 보여주듯 pre-warming을 구성하는 작업 대부분은 애초에 CPU-bound가 아니다 — 다만 **런타임/유저코드 초기화 단계만은 진짜 CPU-bound**이므로, 이 단계를 언제 수행하느냐가 설계의 갈림길이다.

---

## 2. Pre-warming은 어떤 task들로 이루어져 있는가

cold start(= pre-warming이 미리 해두려는 작업 전체)를 논문들이 분해한 단계는 다음과 같다.

| # | Task | 하는 일 | 자원 성격 | 보고된 비용 | 출처 | 등급 |
|---|---|---|---|---|---|---|
| T1 | **스케줄링 / 배치 결정** | 어느 노드에 인스턴스를 놓을지 결정 | control plane, 네트워크 RPC | Huawei 한 리전에선 cold start(최대 7초)를 **dependency 배포 + 스케줄링이 지배** | EuroSys'25 | A |
| T2 | **이미지·코드·의존성 확보** | 컨테이너 이미지 pull, 함수 코드/라이브러리 다운로드 | **네트워크 + 스토리지 I/O**, 대용량 | 커스텀 이미지가 **1.3GB 초과**, 원격 레지스트리에서 받으면 cold start가 **수 분**까지 | FaaSNet, ATC'21 | A |
| T3 | **커널 격리 객체 생성** | namespace(net/IPC/mount), cgroup, rootfs·OverlayFS mount | **커널 경로, 직렬화에 취약**, 개별 비용은 작음 | cgroup 할당 자체는 **100–300µs**; 플랫폼 불변 커널 연산은 startup의 **<1.5%** | Decomposing Docker Startup | A `[preprint]` |
| T4 | **샌드박스/게스트 기동 또는 스냅샷 복원** | microVM boot 또는 checkpoint restore | **디스크 I/O (page fault) 지배** | 스냅샷 복원은 호출당 **수천 page fault**, 비연속 읽기 지배(1편 #17); Firecracker boot ≤125ms | REAP ASPLOS'21 / Firecracker NSDI'20 | A |
| T5 | **언어 런타임 초기화** | JVM/Node/Python 런타임 부팅, JIT | **CPU-bound** | gVisor 기준 **Java 부팅이 e2e 지연의 34–88%**; Catalyzer로는 5% 미만으로 하락 | Catalyzer, ASPLOS'20 | A |
| T6 | **사용자 코드 초기화** | import, 전역 초기화, 연결 수립 | **CPU + I/O 혼합** | 인기 Python 라이브러리 import만으로 **약 100ms** 추가 | SOCK, ATC'18 | A |
| — | *(참고: 단계별 실측 예시)* | OpenLambda 계열 측정 | — | Load Function **10ms** / Resolve Dependencies **3407ms** / Create Sandbox **55ms** / Execute Request **63ms** / Clean Up **6ms** | 2차 인용으로 확인 | **B** |

### 2.1 이 task들의 공통 특징

**(a) 시간의 대부분은 CPU가 아니라 I/O와 커널 대기에 있다.**
플랫폼 불변 커널 연산은 **<1.5%**, 나머지 **550–1850ms**가 스토리지/런타임 의존 연산이다(Decomposing Docker Startup, preprint). T2·T4가 I/O 지배이고, T3는 시간 비중 자체가 작다.

**(b) 그러나 T5·T6은 진짜 CPU를 쓴다.**
Java 런타임 부팅이 e2e의 34–88%를 차지한다는 Catalyzer의 수치가 이를 못 박는다. ▶ 해석: "pre-warming은 I/O만 쓴다"는 주장은 **틀렸다.** 정확한 진술은 *"기동 지연의 대부분은 I/O·커널이지만, CPU를 쓰는 구간(런타임/유저 초기화)이 분명히 존재하며 언어 런타임이 무거울수록 커진다"*이다.

**(c) 개별 비용은 작지만 동시성에서 비선형으로 악화된다.**
cgroup 할당은 100–300µs에 불과하지만(T3), 동시 기동 시 `clone()`이 1.45ms→418ms로 무너진다(1편 #11). 또한 샌드박스 셋업의 커널 작업은 **상당한 스케줄러 활동과 컨텍스트 스위치를 유발해 지연을 증폭시킨다**고 보고된다(Decomposing Docker Startup).

**(d) 그래서 논문들의 처방이 "미리 만들어 풀에 넣기"로 수렴한다** — 1편 §3 표(SOCK/PCPM/RunD/AFaaS) 참조.

---

## 3. 함수 실행 쪽의 특징

| 특징 | 수치 | 출처 | 등급 |
|---|---|---|---|
| 실행이 매우 짧다 | **50%의 함수가 1초 미만**; 일반적으로 수 ms~수 초, ms 단위 과금 | Shahrad ATC'20 / Demystifying Billing | A |
| 할당 자원을 다 못 쓴다 | 과금 vCPU 시간이 실제 CPU 사용의 **1.02–3.99배**, 과금 메모리가 실사용의 **1.95–5.49배** | Demystifying Serverless Costs | A `[preprint]` |
| **짧은 버스트는 CPU 쿼터를 우회한다** | 20ms period / 10ms quota(=0.5 vCPU) cgroup에서 10ms짜리 작업은 **설정된 0.5 vCPU 제한과 무관하게 그 순간 CPU의 100%를 점유**할 수 있다 | Demystifying Serverless Costs | A `[preprint]` |
| 밀집 배치는 컨텍스트 스위치로 무너진다 | 서버리스처럼 조밀하게 채운 워크로드에서 컨텍스트 스위치 오버헤드가 **노드 성능을 심각하게 저하**시킬 수 있음(개별 스위치 비용 증가 + 스위치 빈도 증가 양쪽) | Mitigating context switching in densely packed Linux clusters | A `[preprint]` |
| 스케줄러 선택이 트레이드오프를 만든다 | 짧은 함수에서 **FIFO가 실행시간은 유의미하게 낫지만 응답시간은 유의미하게 나쁨** (CFS는 반대) | In Serverless, OS Scheduler Choice Costs Money | A `[preprint]` |

▶ **해석 — 여기가 이번 조사의 가장 중요한 발견.** 세 번째 행(cgroup 쿼터 우회)은 의뢰 질문에 직접 답한다. **prewarming 작업을 cgroup CPU 쿼터로 묶어두면 안전하다는 통념은, 작업이 쿼터 period보다 짧을 때 성립하지 않는다.** T3(수백 µs)나 짧은 T5 조각은 정확히 그 영역에 있다. 즉 "CPU limit을 걸었으니 다른 함수를 방해하지 않는다"는 방어는 **논문 근거로 반박된다.** 다만 이 근거는 preprint이며, 원 진술은 서버리스 과금 맥락의 일반 서술이므로 prewarming에 적용한 것은 우리 해석이다.

---

## 4. 서버리스 풀의 실제 CPU / 메모리 상태

| 관측 | 수치 | 출처 | 등급 |
|---|---|---|---|
| CPU는 심각하게 남는다 | Alicloud·Huawei Cloud 프로덕션 트레이스에서 서버리스 플랫폼 자원이 **CPU·GPU 모두 심각하게 저활용**; 사용자 할당이 보수적이고 인스턴스가 저부하 | Jiagu, ATC'24 | A |
| 남는 CPU의 규모 | Jiagu는 Kubernetes 대비 **CPU 인스턴스 밀도 54.8% 향상**; Huawei 실트레이스에서 스케줄링 비용 81.0–93.7%↓, cold start 지연 57.4–69.3%↓ | Jiagu, ATC'24 | A |
| 함수는 할당 자원을 저활용 | Huawei 트레이스: 함수들이 할당 자원을 낮게 사용 (트레이스: 내부 워크로드 200개 함수, 234일 중 141일치) | Jiagu / How Does It Function? SoCC'23 | A |
| 메모리는 빡빡하다 | 스케일링 정책 탓 **실사용 대비 2–10× 메모리 할당** | High Cost of Keeping Warm | A `[preprint]` |
| 밀도 한계는 메모리가 결정 | 384GB 노드에 2500개(≈컨테이너당 157MB, ▶계산); 128MB 컨테이너에 Kata-FC 94MB 오버헤드 | RunD, ATC'22 | A |
| CPU와 메모리 사용률은 연동되지 않는다 | CPU 사용률과 메모리 사용률 사이에 **강한 선형 관계가 없다** | Demystifying Serverless Costs | A `[preprint]` |

▶ **해석 — 핵심 비대칭.** 프로덕션 서버리스 풀은 **CPU는 남고 메모리는 모자란** 상태다. 그리고 두 축은 서로 연동되지 않는다. 이것이 pre-warming 판정의 토대다: pre-warming은 **남는 자원(CPU)을 조금 쓰고 모자란 자원(메모리)을 많이 쓰는 거래**다.

---

## 5. 판정 — 충분히 좋은 솔루션인가, 실행을 막는 솔루션인가

### 5.1 "실행을 막지 않는다"에 유리한 근거

1. 풀의 CPU가 심각하게 저활용이라 헤드룸이 존재한다(§4).
2. idle warm 인스턴스는 CPU/전력을 거의 안 쓴다 — 상시 pod 5개 합계 0.20W(1편 #25).
3. pre-warming이 미리 해두려는 작업의 시간 대부분은 CPU가 아니라 I/O·커널이다(§2.1a, 커널 연산 <1.5%).
4. **미리 해두면 동시성 민감도 자체가 사라진다** — pre-craft한 네트워크 자원 사용 시 **동시성이 올라가도 startup time이 flat, 메모리 소모 negligible**(PCPM, HotCloud'19). RunD는 cgroup 사전 생성으로 **동시성이 올라가도 CPU 오버헤드가 소폭만 증가**(ATC'22).
5. 예측 기반 정책은 자원을 **덜** 쓰면서 cold start를 줄인다 — 고정 keep-alive를 지배하며 프로덕션 배포됨(Shahrad ATC'20); IceBreaker는 warm container 17.4%↓·keep-alive 43%↓(ASPLOS'22).

### 5.2 "실행을 막는다"에 유리한 근거

1. **샌드박스 기동/철거가 함수 실행 CPU 사이클의 10–40%**에 해당하는 계산 오버헤드를 만들며, 주로 worker node에서 발생한다(High Cost of Keeping Warm, preprint).
2. **cgroup CPU 쿼터가 짧은 버스트를 막지 못한다**(§3) — 격리로 안전을 확보했다는 가정이 깨진다.
3. 동시 기동은 커널 경로에서 비선형으로 악화된다 — `clone()` 1.45ms→418ms(OSDI'25), Kata 100개 동시에서 rootfs·cgroup 저하(ATC'22), 15개 동시에서 네트워크 셋업 400ms(1편 #16, 등급 B).
4. 샌드박스 셋업의 커널 작업이 **스케줄러 활동과 컨텍스트 스위치를 증폭**시키고(§2.1c), 조밀 배치에서 컨텍스트 스위치는 **노드 성능을 심각하게 저하**시킬 수 있다(§3).
5. **메모리 축출 연쇄 — 가장 직접적인 "실행 방해".** warm pool이 한 테넌트 컨테이너로 점거되면 **다른 테넌트의 컨테이너가 축출되고, 이후 요청이 전부 cold start가 된다**(FaasCamp / Caching Aided Multi-Tenant Serverless, preprint). 또한 동시 요청은 **곧 재사용될 컨테이너를 불균형하게 축출**한다.
6. FaaSCache 계열의 축출 정책은 **서버 자원이 고갈됐을 때만 발동**하도록 설계되어 자원이 넉넉한 일반 배치에는 맞지 않는다는 지적이 있다(같은 preprint).

### 5.3 종합 판정

▶ **해석(우리 판단).**

- **"CPU를 빼앗아 다른 함수를 못 돌게 하는 솔루션"이라는 규정은 논문 근거로 지지되지 않는다.** 풀에 CPU 헤드룸이 있고(§4), 유지 비용은 CPU가 아니며(5.1-2), 작업의 시간 대부분이 CPU가 아니다(§2.1a). 게다가 pre-warming이 겨냥하는 비싼 커널 작업은 미리 해두면 **오히려 사라지는** 비용이다(5.1-4).
- **그러나 "충분히 좋은 솔루션"이라고 무조건 말할 수도 없다.** 세 가지 조건이 붙는다:
  1. **동시 기동 수를 제한할 것.** 지연 폭발은 총량이 아니라 동시성의 함수다(5.2-3).
  2. **메모리를 1급 예산으로 다룰 것.** 실제로 다른 함수의 실행을 막는 경로는 CPU가 아니라 **warm pool 축출 연쇄**다(5.2-5). CPU 헤드룸이 있다고 해서 메모리 헤드룸이 있는 것이 아니다 — 두 사용률은 연동되지 않는다(§4).
  3. **CPU 격리를 과신하지 말 것.** cgroup 쿼터는 period보다 짧은 버스트를 막지 못한다(5.2-2).
- **가장 정확한 한 줄:** pre-warming은 *남는 CPU를 조금 쓰고 모자란 메모리를 많이 쓰는 거래*이며, 실패하는 방식은 "CPU 고갈"이 아니라 **"메모리 축출로 인한 cold start 연쇄"**와 **"동시 기동 버스트의 커널 직렬화"**다.

---

## 6. 남는 공백과 측정 제안

1편 §7에서 지적한 공백이 이번 조사에서도 메워지지 않았다. **pre-warming 활동이 같은 노드에서 실행 중인 함수의 실행시간을 실제로 몇 ms 늘리는지를 직접 측정한 논문을 찾지 못했다.** 5.2의 근거들은 모두 (a) 노드 총 CPU 사이클 비율(10–40%), (b) 기동 자신의 지연, (c) 축출로 인한 *후속* cold start를 측정한 것이지, **동시 실행 중인 victim의 slowdown**이 아니다.

▶ **제안(논문 근거 아님).** 이 양은 PureTime이 직접 산출하는 형태와 정확히 일치한다 — prewarm 기동 cgroup을 noise 유발자, 실행 중 함수를 victim으로 두면 *prewarm이 victim의 wall-clock에서 어느 자원으로 몇 ms를 빼앗았는지*를 per-invocation으로 분해할 수 있다. §2의 task 분해가 그대로 가설이 된다:

| 가설 | 예상 관측 | 근거 |
|---|---|---|
| T3(커널 객체 생성)는 CPU wait을 만들지만 총량은 작다 | 동시 기동 수에 민감, 평상시 미미 | §2.1c, 커널 연산 <1.5% |
| T4(스냅샷 복원)는 block wait을 만든다 | block wait이 지배적 | 1편 #17 |
| T5(런타임 초기화)는 실제 CPU wait을 만든다 | 언어 런타임이 무거울수록 큼 | Catalyzer 34–88% |
| 짧은 버스트는 쿼터를 넘겨 CPU wait을 만든다 | 쿼터 설정과 무관한 wait 관측 | §3 |

단, 프로젝트의 측정 전제(단일 코어 pinning, block은 io controller 위임 + `queue_depth=2` + 채워진 디스크, network는 TCP-TX 한정)와 컨테이너 기동이 충돌할 소지가 있어 별도 설계 검토가 필요하다. 특히 **컨테이너 기동은 cgroup을 새로 만드는 행위**이므로, cgroup id 기반 귀속을 쓰는 PureTime에서 "생성 중인 cgroup"을 어떻게 다룰지가 선결 과제다.

---

## 7. 참고문헌 (1편에 없던 것만)

**Peer-reviewed**
1. A. Wang et al. **"FaaSNet: Scalable and Fast Provisioning of Custom Serverless Container Runtimes at Alibaba Cloud Function Compute."** USENIX ATC 2021. https://www.usenix.org/conference/atc21/presentation/wang-ao · arXiv:2105.11229
2. D. Du et al. **"Catalyzer: Sub-millisecond Startup for Serverless Computing with Initialization-less Booting."** ASPLOS 2020. https://dl.acm.org/doi/10.1145/3373376.3378512
3. Q. Liu et al. **"Harmonizing Efficiency and Practicability: Optimizing Resource Utilization in Serverless Computing with Jiagu."** USENIX ATC 2024. https://www.usenix.org/conference/atc24/presentation/liu-qingyuan · arXiv:2403.00433
4. A. Eismann et al. **"How Does It Function? Characterizing Long-term Trends in Production Serverless Workloads."** ACM SoCC 2023. https://dl.acm.org/doi/10.1145/3620678.3624783 · arXiv:2312.10127
5. D. Schall, A. Margaritov, D. Ustiugov, A. Sandberg, B. Grot. **"Lukewarm Serverless Functions: Characterization and Optimization."** ISCA 2022. *(제목·저자·venue만 확인, 수치는 본문에 인용하지 않음)*

**Preprint (peer-review 미확인)**
6. **"Demystifying Serverless Costs on Public Platforms: Bridging Billing, Architecture, and OS Scheduling."** arXiv:2506.01283
7. **"Caching Aided Multi-Tenant Serverless Computing" (FaasCamp).** arXiv:2408.00957
8. **"Mitigating Context Switching in Densely Packed Linux Clusters with Latency-Aware Group Scheduling."** arXiv:2508.15703
9. **"In Serverless, OS Scheduler Choice Costs Money: A Hybrid Scheduling Approach for Cheaper FaaS."** arXiv:2411.08448
10. **"Decomposing Docker Container Startup Performance: A Three-Tier Measurement Study on Heterogeneous Infrastructure."** arXiv:2602.15214 *(1편과 공용)*
11. **"The High Cost of Keeping Warm: Characterizing Overhead in Serverless Autoscaling Policies."** arXiv:2509.03104 *(1편과 공용)*
