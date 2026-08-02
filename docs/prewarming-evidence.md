# 서버리스 Pre-warming의 효용성 — 논문 근거 조사

**조사 질문 (의뢰 원문)**
1. 예측해서 미리 컨테이너를 올려놓는 것(predictive pre-warming)이 가치가 있는가?
2. 미리 올리느라 CPU를 잡아먹어서, 정작 실행되어야 할 다른 함수가 늦어지는 것 아닌가?
3. Cold start 시 컨테이너를 띄우는 작업의 자원 패턴/사용량은 **CPU / storage / memory 중 어느 layer에서 걸리는가** — 이를 근거로 "pre-warming이 함수 서빙에 큰 영향을 주지 않으면서 띄워놓을 수 있다"는 증거가 성립하는가?

---

## 0. 이 문서의 근거 기준과 검증 한계 (먼저 읽을 것)

**근거 기준.** 아래 모든 주장은 학술 논문(peer-reviewed 또는 arXiv preprint)에 보고된 내용만으로 구성했다. 벤더 블로그·기술 아티클·추정치는 근거로 쓰지 않았다. 논문 진술이 아닌 문장은 예외 없이 `▶ 해석` 으로 표시했다.

**⚠ 검증 한계 (중요).** 이 세션의 egress 정책이 usenix.org / arxiv.org / dl.acm.org / ar5iv / 저자 개인 페이지에 대한 접근을 **전부 차단**(CONNECT 403)했다. 따라서 **원문 PDF를 직접 열어 확인하지 못했고**, 근거는 각 논문 PDF를 색인한 검색 결과의 스니펫이다. 결과적으로:

- 표의 수치는 **해당 논문에 귀속된 것으로 검색 결과가 명시한 값**이며, 페이지·표·그림 번호까지는 확정하지 못했다.
- 각 항목에 **검증 등급**을 붙였다: `A` = 논문 PDF 색인 스니펫에서 해당 논문에 직접 귀속 / `B` = 논문에 귀속되나 2차 인용(다른 논문이 인용한 형태)이라 원문 재확인 필요.
- **인용 전 재확인 필수.** 이 문서를 논문 본문·리뷰 대응에 쓸 경우, 네트워크가 열린 환경에서 `A` 등급도 원문 대조 후 인용할 것. (프로젝트 규칙: `docs/claims-experiments-contract.md`의 "인용 정확성 책임"과 동일한 기준을 적용.)
- peer-review를 거치지 않은 **arXiv preprint는 표에 `[preprint]`로 표시**했다. 핵심 결론 중 하나(§3의 churn CPU 10–40%)가 preprint에 의존하므로, 이 항목은 특히 재확인이 필요하다.

---

## 1. 결론 요약

**Q1. 예측 pre-warming은 가치가 있는가 → 조건부로 있다. 단, "모든 함수에 대해"는 논문 근거로 지지되지 않는다.**
Azure 프로덕션 워크로드에서 호출 간격(IAT) 히스토그램 기반 정책이 고정 keep-alive를 지배(cold start 감소 + 자원 소모 감소)했고 **프로덕션에 실제 배포**되었다(Shahrad, ATC'20). 반면 SoCC'24 vision paper는 **함수의 80% 이상이 의미상 latency-sensitive하지 않다**고 보고하여, 가치의 적용 범위를 좁힌다.

**Q2. "미리 올리느라 CPU를 잡아먹어 다른 함수가 늦어진다" → 비용은 실재하지만, 원인이 CPU 처리량이 아니다.**
인스턴스 churn의 계산 오버헤드는 요청 처리에 쓰인 **CPU 사이클의 10–40%**에 달한다(preprint). 그러나 고동시성에서 실제로 폭발하는 것은 CPU 대역폭이 아니라 **커널 객체 생성의 직렬화**다: `clone()` 지연이 **1.45ms → 최악 418ms**로 악화되며 원인은 새 network/IPC namespace 요청이다(OSDI'25). 그리고 이 문제의 논문상 해법이 정확히 **"미리 만들어 풀에 넣어두는 것"**이다 — pre-craft한 네트워크 자원을 쓰면 **동시성이 올라가도 startup time이 flat, 메모리 소모는 negligible**(HotCloud'19).
▶ 해석: 즉 pre-warming은 이 직렬화를 *유발*하는 쪽이 아니라 *임계경로와 부하 피크에서 빼내는* 쪽에 가깝다. 단, 예측이 틀려 churn이 늘면 위 10–40% 비용을 그대로 지불한다.

**Q3. 어느 layer에서 걸리는가 → 청구서는 memory(용량), 지연은 storage(page fault I/O), CPU는 "burst 시 커널 직렬화" 형태로만 나타난다.**
- **Memory = binding constraint.** 128MB 컨테이너 하나에 Kata-FireCracker 기준 **94MB**의 오버헤드, 노드 **384GB에 2500개**가 밀도 한계(ATC'22). 스케일링 정책 탓에 실사용 대비 **2–10배** 메모리가 할당된다(preprint).
- **Storage = cold start 지연의 지배 요인.** 스냅샷 복원은 **수천 개의 page fault**를 비연속 디스크 읽기로 처리하며, 이 때문에 스냅샷 기동 실행시간이 memory-resident 대비 **평균 95% 높다**(ASPLOS'21). 스토리지 tier 차이가 **2.04×**(HDD 1157ms vs SSD 568ms)인 반면 **이미지 크기는 5MB→155MB에서 2.5%만** 영향(preprint).
- **CPU = idle 상태에서는 거의 0.** 상시 대기 pod 5개가 합쳐 **0.20W / 550MiB 이상**을 소모 — 전력(CPU)은 무시할 수준이고 메모리만 실질 비용(UCC'25, edge 클러스터).

**따라서 의뢰가 요구한 "증거"의 형태는 이렇게 성립한다:** warm 상태로 *유지*하는 비용은 CPU가 아니라 메모리이고(§4.3), 컨테이너를 *띄우는* 순간의 비용은 CPU 처리량이 아니라 커널 경로 직렬화와 디스크 page fault이며(§4.1–4.2), 이 두 가지는 모두 **동시성을 제한하고 커널 객체를 미리 풀링하면 평탄화된다**는 것이 여러 프로덕션 시스템 논문의 공통 결론이다(§5).

**⚠ 단, 결정적 공백이 하나 있다(§7): pre-warming 작업이 "같은 노드에서 지금 실행 중인 다른 함수의 실행시간"에 주는 간섭을 직접 측정한 논문을 이번 조사에서 찾지 못했다.** 위 근거들은 전부 (a) startup 자신의 지연, (b) 노드 총 자원 소모, (c) 밀도 한계를 측정한 것이지, co-running victim의 slowdown을 측정한 것이 아니다.

---

## 2. 근거 표 (주장 ↔ 논문 ↔ 수치)

| # | 주장 | 수치 | 출처 | 등급 |
|---|---|---|---|---|
| 1 | 대부분의 함수는 매우 드물게 호출된다 | 애플리케이션의 **81%가 분당 1회 이하** 호출, **45%는 평균 시간당 1회 이하** | Shahrad, ATC'20 | A |
| 2 | 호출량은 소수 함수에 집중된다 | 상위 **18.6%** 인기 앱이 전체 호출의 **99.6%** | Shahrad, ATC'20 | A |
| 3 | 함수 실행 자체가 짧다 → cold start가 상대적으로 지배적 | **50%의 함수가 1초 미만** 실행, 함수 메모리 사용량은 4× 범위 | Shahrad, ATC'20 | A |
| 4 | 고정 keep-alive는 자원을 낭비한다 | 고정 2시간 keep-alive는 10분 baseline 대비 **wasted memory time 약 30% 증가**; 10분 keep-alive에서 75th-pct 앱은 **50.3%가 cold start**, 1시간이면 25%로 감소 | Shahrad, ATC'20 | A |
| 5 | 히스토그램 기반 pre-warming + 가변 keep-alive가 고정 정책을 지배 | 앱별 IAT 히스토그램으로 pre-warm window(=최소 간격)와 keep-alive window(=히스토그램 폭)를 설정; cold start를 줄이면서 자원은 덜 씀. **프로덕션 배포됨** | Shahrad, ATC'20 | A |
| 6 | 예측 기반 warming의 정량 이득 | Azure trace에서 warm container 수 **17.4%↓**, keep-alive 지속시간 **43%↓** (OpenWhisk 기본 10분 정책 대비); 합성 워크로드에선 각각 14.8%↓, 11.3%↓ | IceBreaker, ASPLOS'22 | A |
| 7 | 상용 플랫폼이 실제로 pre-warming을 한다 | Azure는 keep-alive가 **120–360초로 가변**인 opportunistic 전략으로 보이며, **일정 간격으로 cold start가 발생하면 pre-warm** 수행 | Serverless Cold Starts and Where to Find Them, EuroSys'25 | A |
| 8 | 프로덕션 cold start의 크기와 구성은 지역/구성마다 다르다 | Huawei 트레이스(**85B 요청, 11.9M cold start**): 한 리전은 최대 **7초**(dependency 배포+스케줄링 지배), 다른 리전은 최대 **3초**(pod allocation 지배) | 위와 동일, EuroSys'25 | A |
| 9 | **[반대 근거]** cold start 최적화의 가치 자체에 대한 반론 | 35편 분석 결과 **함수의 80% 이상이 의미상 latency-sensitive하지 않음**; 다수가 non-interactive 워크로드 | Is It Time To Put Cold Starts In The Deep Freeze?, SoCC'24 | A |
| 10 | **[핵심 비용]** 인스턴스 churn은 실제로 CPU를 먹는다 | 인스턴스 churn의 계산 오버헤드가 **요청 처리에 쓴 CPU 사이클의 10–40%**에 해당하며 주로 worker node에서 발생; 스케일링 정책 탓에 **실사용 대비 2–10배 메모리** 할당 | The High Cost of Keeping Warm, arXiv 2509.03104 | A `[preprint]` |
| 11 | **[핵심 기전]** 고동시성에서 폭발하는 건 커널 객체 생성이다 | sandbox fork 단계의 `clone()` 지연이 **1.45ms → 최악 418ms**로 악화; 주 원인은 새 **network/IPC namespace** 요청 | Fork in the Road (AFaaS), OSDI'25 | A |
| 12 | 동시 기동 시 rootfs/cgroup이 병목이 된다 | **100개 이상** Kata 컨테이너 동시 기동 시 rootfs·cgroup 생성에서 뚜렷한 성능 저하; host cgroup + guest OS + rootfs가 함께 밀도·기동성능을 악화 | RunD, ATC'22 | A |
| 13 | cgroup 연산은 "compute-intensive"로 분류된다 | RunD는 **cgroup 사전 생성**과 read/write split으로 cgroup의 compute-intensive 연산을 줄였고, 그 결과 **동시성이 올라가도 CPU 오버헤드가 소폭만 증가** | RunD, ATC'22 | A |
| 14 | 커널 확장성 병목 회피만으로 기동이 한 자릿수 배 빨라진다 | 커널 확장성 병목 회피로 Docker 대비 **18×**, generalized-Zygote로 추가 **3×**, 3-tier 캐싱으로 **45×**; Python 인기 라이브러리 import만으로 **약 100ms** 추가 | SOCK, ATC'18 | A |
| 15 | **[핵심 반증]** 미리 만들어 두면 동시성에 둔감해진다 | 네트워크 자원을 **pre-craft**해 pause container pool(PCPM)에 두고 동적으로 재결합 → cold start **order of magnitude** 개선, **메모리 소모 negligible**, **동시성이 올라가도 startup time이 flat** | Agile Cold Starts, HotCloud'19 | A |
| 16 | 네트워크 셋업은 동시성에 취약하다 | **15개 인스턴스 동시 기동 시 네트워크 셋업 시간 400ms** (PCPM 미적용 baseline) | Mohan et al. 인용 형태로 확인 | **B** (원문 재확인 필요) |
| 17 | **[storage]** 스냅샷 복원은 page fault/디스크 I/O가 지배한다 | 기존 스냅샷은 guest memory를 on-demand로 채워 **호출당 수천 개 page fault** 발생, 스냅샷 파일의 **비연속** 페이지를 하나씩 읽음 → 지연은 **CPU가 아니라 디스크 I/O가 지배**. 스냅샷 기동 실행시간은 memory-resident 대비 **평균 95% 높음** | REAP, ASPLOS'21 | A |
| 18 | working set은 안정적이라 예측·프리페치가 가능하다 | 같은 함수의 서로 다른 호출은 **동일한 stable working set** 페이지를 접근 → WS를 연속 파일로 모아 프리페치하면 cold start **평균 3.7× 단축** | REAP, ASPLOS'21 | A |
| 19 | **[storage]** 병목은 스토리지 속도가 아니라 OS 메모리 프리미티브 | "OS-level limitations, **not storage speed**, are the real barrier to ultra-fast restores from disk"; 커널 메모리 기전 재설계로 cold restore **5ms 미만** | Taming Serverless Cold Starts Through OS Co-Design (Spice), arXiv 2509.14292 | A `[preprint]` |
| 20 | **[storage]** 이미지 크기보다 런타임 오버헤드가 지배한다 | 이미지 **5MB→155MB**에서 startup 변동은 **2.5%**에 불과(SSD); 스토리지 tier는 **2.04× 페널티**(HDD 1157ms vs SSD 568ms) | Decomposing Docker Container Startup Performance, arXiv 2602.15214 | A `[preprint]` |
| 21 | **[memory]** 가상화 자체의 메모리 오버헤드는 작다 | Firecracker VMM 스레드 메모리 오버헤드 **5MiB 미만**(1 vCPU/128MiB microVM), boot **≤125ms**, 호스트당 **초당 150 microVM** 생성 가능 | Firecracker, NSDI'20 | A |
| 22 | **[memory]** 그러나 컨테이너 단위 실효 오버헤드는 크다 | **128MB 컨테이너의 메모리 오버헤드가 Kata-FireCracker 94MB / Kata-qemu 168MB** | RunD, ATC'22 | A |
| 23 | **[memory]** 밀도 한계는 메모리가 결정한다 | RunD로 **초당 200개 이상** secure container 기동, **384GB 노드에 2500개 이상** 배포 (→ ▶ 계산: 컨테이너당 약 157MB) | RunD, ATC'22 | A |
| 24 | **[memory]** warm 유지 비용이 곧 메모리 비용임을 전제로 한 연구 계열 | keep-alive를 캐싱 문제로 보고 Greedy-Dual 정책으로 cold start 오버헤드 **3× 이상** 감소(FaasCache); warm sandbox 메모리에 중복이 많아 dedup한 "dedup state"로 메모리 압박 시 **최대 3.8×** e2e 개선, cold start **10–50%** 감소(Medes) | FaasCache ASPLOS'21 / Medes EuroSys'22 | A |
| 25 | **[CPU]** idle warm 인스턴스는 CPU/전력을 거의 안 쓴다 | 상시 대기 pod 5개가 **합계 0.20W, 550MiB 이상**; 개별 서비스는 **0.05W 미만** (Raspberry Pi 엣지 클러스터 측정) | Energy-Aware Latency Optimization…, UCC'25 | A (엣지 환경 한정) |

---

## 3. Q2에 대한 정면 답변 — "CPU 잡아먹어서 다른 함수가 늦어지는가"

의뢰의 직관은 **절반은 논문으로 지지되고, 절반은 기전이 다르다.**

**지지되는 절반.** 인스턴스를 만들고 없애는 churn은 공짜가 아니다. 요청 처리 CPU 사이클의 **10–40%**에 해당하는 계산 오버헤드가 발생하며, 이는 control plane이 아니라 **worker node**에서 나온다(#10, preprint). 같은 논문은 sandbox 관리와 자원 할당이 주된 오버헤드 원천이므로 최적화는 control plane이 아니라 그쪽을 봐야 한다고 결론짓는다.

**기전이 다른 절반.** 고동시성에서 실제로 터지는 것은 "CPU가 모자라서"가 아니라 **커널 객체 생성이 직렬화되어서**다.

- `clone()` 한 번이 **1.45ms에서 최악 418ms**로 늘어나며, 원인은 새 **network/IPC namespace** 요청이다(#11, OSDI'25). 약 **288배** 악화다(▶ 계산).
- Kata 컨테이너 **100개 이상**을 동시에 띄우면 rootfs·cgroup 생성에서 뚜렷한 저하가 나타난다(#12, ATC'22).
- SOCK은 이 문제를 "커널 확장성 병목"으로 규정하고, 그것만 피해도 Docker 대비 **18×**를 얻었다(#14, ATC'18).

**그리고 이 문제의 논문상 해법이 정확히 pre-warming의 형태다.** 위 논문들이 내놓은 처방은 모두 *비싼 커널 객체를 미리 만들어 풀에 넣고 재사용하는 것*이다:

| 시스템 | 미리 만들어 두는 대상 | 보고된 효과 |
|---|---|---|
| SOCK (ATC'18) | cgroup 캐시, Zygote 컨테이너 | Docker 대비 18×, Zygote로 추가 3× |
| PCPM (HotCloud'19) | 네트워크 자원(pause container pool) | cold start order-of-magnitude 개선, **메모리 negligible**, **동시성에도 startup flat** |
| RunD (ATC'22) | cgroup 사전 생성 | 초당 200+ 기동, **동시성 증가에도 CPU 오버헤드 소폭 증가에 그침** |
| AFaaS (OSDI'25) | cgroup pool, namespace 공유 | cold start 밀리초 수준, 24× 동시성에서 **<15ms**, 메모리 **최대 84.9%↓** |

▶ **해석(논문 진술 아님).** 이 표가 의뢰 질문에 대한 가장 강한 형태의 답이다. "미리 올려두는 행위"가 다른 함수를 늦출까 봐 걱정한 바로 그 비용(namespace/cgroup 생성)은, **미리 해두었을 때 오히려 사라지는** 비용이다. 위험한 것은 pre-warming 자체가 아니라 **동시에 대량으로 기동하는 것**이다 — #11·#12가 보여주듯 지연 폭발은 동시성의 함수이지 총량의 함수가 아니다. 따라서 rate-limit된 예측 기반 pre-warming과, 부하 피크에 몰리는 reactive 대량 기동은 CPU 관점에서 전혀 다른 사건이다.

**다만 정직하게 남는 위험 두 가지 (둘 다 논문 근거 있음):**
1. **예측이 틀리면 churn이 늘고, churn은 CPU를 먹는다**(#10). pre-warming의 CPU 비용은 곧 **예측 정확도의 함수**다.
2. **메모리 압박은 간접적으로 성능을 해친다.** Medes는 메모리 압박 상황에서 dedup으로 최대 3.8× e2e 개선을 보였는데(#24), 이는 뒤집어 말하면 warm 인스턴스를 과다 보유해 메모리가 부족해지면 그만큼 손해가 난다는 뜻이다.

---

## 4. Q3에 대한 정면 답변 — layer별 자원 패턴

### 4.1 CPU layer
- **Idle warm 상태: 거의 0.** 상시 대기 pod 5개 합계 0.20W, 개별 0.05W 미만(#25, 엣지 측정).
- **기동 순간: 커널 경로에 집중.** cgroup 연산은 compute-intensive로 분류되며(#13), namespace 생성이 동시성 하에서 직렬화된다(#11).
- **총량: churn이 요청 처리 CPU의 10–40%**(#10, preprint).
- ▶ 해석: CPU는 **평균 사용량이 아니라 동시성 피크에서만** 문제가 된다.

### 4.2 Storage layer
- **cold start 지연의 지배 요인.** 스냅샷 복원은 호출당 수천 개 page fault를 **비연속 디스크 읽기**로 처리하며, 지연은 CPU가 아니라 디스크 I/O가 지배한다(#17).
- **크기보다 접근 패턴이 중요.** 이미지 5MB→155MB 변화는 startup의 2.5%만 좌우하지만(#20), 디스크 tier는 2.04× 차이를 만든다(#20). REAP는 working set을 **연속 파일 한 번의 read**로 바꿔 3.7×를 얻었다(#18).
- 최신 preprint는 한 발 더 나가 **"병목은 스토리지 속도가 아니라 OS 메모리 프리미티브"**라고 주장한다(#19).
- ▶ 해석: pre-warming을 미리(=한가할 때) 수행하면 이 I/O를 **임계경로 밖의 순차 I/O로** 옮길 수 있다는 것이 #18의 함의다. 단 이는 REAP의 프리페치 설계에 대한 진술이지, "prewarm이 co-tenant I/O를 방해하지 않는다"는 측정은 아니다.

### 4.3 Memory layer — **진짜 청구서**
- 하이퍼바이저 자체는 싸다(Firecracker VMM <5MiB, #21). 그러나 **컨테이너 단위 실효 오버헤드는 128MB 컨테이너에 94MB**(Kata-FC)로 크다(#22).
- **밀도 한계가 메모리로 결정된다**: 384GB 노드에 2500개(#23).
- **스케일링 정책이 실사용 대비 2–10배 메모리를 잡는다**(#10).
- warm 유지 비용을 메모리 문제로 정식화한 연구 계열이 별도로 존재한다(FaasCache의 캐싱 정식화, Medes의 dedup, #24).

**layer 결론:** *유지* 비용 = 메모리, *기동* 지연 = storage I/O + 커널 직렬화, *CPU* = 동시성 피크에서만. 의뢰가 찾던 "CPU를 크게 건드리지 않으면서 띄워둘 수 있다"는 주장은 **idle warm 상태에 대해서는 논문 근거로 성립하고(#25, #21), 기동 순간에 대해서는 '동시성을 제한하고 커널 객체를 풀링한다는 조건 하에' 성립한다(#13, #15).**

---

## 5. 논문 근거로 도출되는 설계 규칙

| 규칙 | 근거 |
|---|---|
| 비싼 커널 객체(netns/cgroup)는 풀에 미리 만들어 재사용한다 | #14, #15, #13, #11 — 4개 시스템이 독립적으로 같은 처방, 그중 2개는 프로덕션 배포 |
| pre-warm 기동은 **속도 제한·시간 분산**한다 | #11(1.45→418ms), #12(100개 동시), #16(15개 동시에 400ms) — 지연 폭발은 동시성의 함수 |
| 용량 예산은 **메모리**로 잡는다 | #22, #23, #10(2–10× 과할당) |
| 스냅샷은 working set 프리페치로 **순차 I/O화**한다 | #17, #18 |
| 대상 선정은 **예측 가능한 소수**로 좁힌다 | #1·#2(호출 편중), #5(히스토그램), #7(Azure 실사용) |
| 예측 정확도를 CPU 예산과 동일시한다 | #10 — 오탐 churn = CPU 낭비 |

---

## 6. 반대·완화 근거 (반드시 함께 볼 것)

1. **가치의 범위 축소.** 함수의 80% 이상이 의미상 latency-sensitive하지 않다(#9, SoCC'24). ▶ 해석: pre-warming의 편익은 전체 함수가 아니라 interactive subset에 한정해 주장해야 한다.
2. **호출 편중.** 상위 18.6%가 호출의 99.6%를 차지한다(#2). ▶ 해석: 편익이 큰 대상은 소수이고, cold start를 자주 겪는 다수(81%가 분당 1회 이하, #1)는 예측 난도가 높다 — 즉 "예측하기 쉬운 것"과 "cold start가 잦은 것"이 어긋난다.
3. **churn 비용의 실재**(#10). preprint 근거이므로 인용 시 주의.
4. **환경 의존성이 크다.** 같은 플랫폼도 리전에 따라 cold start 구성 자체가 다르다(#8: 7초/dependency 지배 vs 3초/pod allocation 지배). ▶ 해석: 단일 노드 실험 결과를 일반화하면 안 된다.

---

## 7. 이번 조사로 **메워지지 않은 공백** (가장 중요)

의뢰의 핵심 질문 — *"pre-warming 때문에 지금 실행 중인 다른 함수가 늦어지는가"* — 에 대해 **co-running victim 함수의 실행시간 열화를 직접 측정한 논문을 찾지 못했다.**

수집된 근거들이 실제로 측정한 것은 각각 다음이며, 모두 위 질문과 다른 양이다:
- startup **자신의** 지연 (#11, #12, #14, #15, #16)
- 노드 **총** 자원 소모 (#10, #25)
- 배포 **밀도** 한계 (#22, #23)

▶ **해석 및 제안(논문 근거 아님, 우리 주장).** 이 공백은 PureTime이 직접 겨냥하는 양이다. PureTime은 CPU·network-TX·block·softirq의 대기 시간을 **co-tenant cgroup에 귀속**시키고 겹침을 interval merge로 제거해 **per-invocation noise-free makespan**을 낸다. 따라서 "prewarm 기동 cgroup"을 noise 유발자로, "실행 중 함수"를 victim으로 두면, 위 공백을 정확히 그 형태 — *prewarm 활동이 victim의 wall-clock 중 몇 ms를, 어느 자원에서 빼앗았는가* — 로 측정할 수 있다. §4의 layer 분석이 예측하는 바(CPU wait는 동시 기동 수에 민감, block wait은 스냅샷 복원 I/O에서 발생, 평상시엔 둘 다 미미)를 그대로 가설로 세울 수 있다.
단, 이는 **본 조사가 근거로 확인한 사실이 아니라 후속 실험 제안**이다. 실제로 하려면 프로젝트의 측정 전제(단일 코어 pinning, block은 io controller 위임 + `queue_depth=2` + 채워진 디스크, network는 TCP-TX 한정)를 그대로 지켜야 하며, 특히 컨테이너 기동은 이 전제들과 충돌할 소지가 있으므로 별도 설계 검토가 필요하다.

---

## 8. 참고문헌

**Peer-reviewed**
1. M. Shahrad et al. **"Serverless in the Wild: Characterizing and Optimizing the Serverless Workload at a Large Cloud Provider."** USENIX ATC 2020. https://www.usenix.org/conference/atc20/presentation/shahrad · arXiv:2003.03423
2. D. Ustiugov, P. Petrov, M. Kogias, E. Bugnion, B. Grot. **"Benchmarking, Analysis, and Optimization of Serverless Function Snapshots" (REAP).** ASPLOS 2021. arXiv:2101.09355
3. E. Oakes et al. **"SOCK: Rapid Task Provisioning with Serverless-Optimized Containers."** USENIX ATC 2018. https://www.usenix.org/conference/atc18/presentation/oakes
4. A. Agache et al. **"Firecracker: Lightweight Virtualization for Serverless Applications."** USENIX NSDI 2020. https://www.usenix.org/system/files/nsdi20-paper-agache.pdf
5. Z. Li et al. **"RunD: A Lightweight Secure Container Runtime for High-density Deployment and High-concurrency Startup in Serverless Computing."** USENIX ATC 2022. https://www.usenix.org/conference/atc22/presentation/li-zijun-rund
6. X. Chai et al. **"Fork in the Road: Reflections and Optimizations for Cold Start Latency in Production Serverless Systems" (AFaaS).** USENIX OSDI 2025. (Tsinghua Univ. + Ant Group) https://www.usenix.org/conference/osdi25/presentation/chai-xiaohu
7. A. Mohan, H. Sane, K. Doshi, S. Edupuganti, N. Nayak, V. Sukhomlinov. **"Agile Cold Starts for Scalable Serverless."** USENIX HotCloud 2019. https://www.usenix.org/conference/hotcloud19/presentation/mohan
8. **"Serverless Cold Starts and Where to Find Them."** EuroSys 2025. https://dl.acm.org/doi/10.1145/3689031.3696073 · arXiv:2410.06145
9. **"Is It Time To Put Cold Starts In The Deep Freeze?"** ACM SoCC 2024 (vision paper). https://dl.acm.org/doi/10.1145/3698038.3698527
10. A. Fuerst, P. Sharma. **"FaasCache: Keeping Serverless Computing Alive with Greedy-Dual Caching."** ASPLOS 2021. https://dl.acm.org/doi/10.1145/3445814.3446757
11. D. Saxena et al. **"Memory Deduplication for Serverless Computing with Medes."** EuroSys 2022. https://dl.acm.org/doi/10.1145/3492321.3524272
12. R. B. Roy et al. **"IceBreaker: Warming Serverless Functions Better with Heterogeneity."** ASPLOS 2022. https://dl.acm.org/doi/10.1145/3503222.3507750
13. **"Energy-Aware Latency Optimization for Scheduling Serverless Workload in Edge Computing Environment."** IEEE/ACM UCC 2025. https://dl.acm.org/doi/10.1145/3773274.3774276

**Preprint (peer-review 미확인 — 인용 시 명시할 것)**
14. **"The High Cost of Keeping Warm: Characterizing Overhead in Serverless Autoscaling Policies."** arXiv:2509.03104
15. **"Taming Serverless Cold Starts Through OS Co-Design" (Spice).** arXiv:2509.14292
16. **"Decomposing Docker Container Startup Performance: A Three-Tier Measurement Study on Heterogeneous Infrastructure."** arXiv:2602.15214
