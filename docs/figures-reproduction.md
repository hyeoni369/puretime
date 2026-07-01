# Figure 재현 매뉴얼

논문(`sigconf.tex`)의 **데이터-기반 figure 10종**을 재생성하는 방법.
데이터가 이미 있으면 `experiments/make_all_figures.sh` 한 번으로 전부 재생성된다.
데이터를 새로 **측정**하려면 각 `exp_*.sh`를 돌린 뒤(아래 §측정 주의사항 필수) plot을 다시 실행한다.

수동/외부 그림(`architecture`, `wait-model-a`, `wait-model-b`, `merge`, `trace_for_cv`, `sampleteaser`)은
생성 스크립트가 없으므로 별도 관리한다(건드리지 않음).

## 전체 재생성 (데이터가 있을 때)

```sh
bash experiments/make_all_figures.sh            # -> experiments/figures/*.pdf (10종)
```

## figure ↔ 스크립트 ↔ 데이터 매핑

| sigconf figure | 스크립트 | 데이터 | 재현값(sanity) |
|---|---|---|---|
| `accuracy_baseline`* | `plot_accuracy_normalized.py` | `data/accuracy_7victim/{cpu_float,cpu_factors,cpu_sequential,cpu_aes,net_uploader,net_s3}.csv` + `data/accuracy_K50/results.csv`(block) | removal **91–98%** (pairwise) |
| `robustness` | `plot_exp1b_robustness.py` | `--acc data/accuracy_K50/accuracy_results.csv` `--net data/robustness_1b/results.csv` | CPU 98–99% |
| `interval_merge_scatter` | `plot_exp2_interval_merge.py` | `data/mixed_noise/results.csv` | merge 유효 |
| `input_variance_face`, `input_variance_float` | `plot_exp3_input_variance.py` | `data/reexp_input_variance/results.csv` | 복원오차 3–5% |
| `baseline_cloudwatch_2band`, `baseline_kpa` | `plot_exp4_baseline.py --victim face` | `data/reexp_input_variance/results.csv` (exp3와 동일) | false-alarm 63/80 vs 0/80; band 3.9× |
| `overhead_resource` | `plot_overhead_resource.py` | `data/overhead/overhead_resource.csv` | CPU <0.13%, RSS 0.075% |
| `overhead_e2e` | `plot_overhead_e2e.py` | `data/overhead_e2e/results.csv` | 7 victim <2% 양수 |
| `overhead_nodeload` | `plot_overhead_nodeload.py` | `data/overhead_nodeload/results.csv` | node-load 대비 flat |

\* sigconf는 아직 `figure/accuracy_baseline`을 참조하지만 **최신 figure는 `accuracy_normalized.pdf`**다.
tex의 `\includegraphics{figure/accuracy_baseline}`를 `accuracy_normalized`로 바꾸거나 파일명을 맞춘다.

## 측정 주의사항 (데이터 정확성 — 이걸 어기면 figure가 틀어진다)

1. **accuracy — pairwise 필수.** `plot_accuracy_normalized.py`의 removal·bar는 각 noisy를 *같은 iteration*의
   solo로 정규화(pairwise)한다. block(compression)은 HDD drift로 solo가 iteration마다 1972~3305ms로 흔들려,
   aggregate median/median으로는 PureTime bar가 **1.04(98% 착시)**로 나온다. pairwise면 **1.20(removal 91%)**로
   정확하다. (CPU/Net은 drift가 작아 aggregate와 거의 동일.)

2. **input_variance — `reexp_iv_face`를 쓰지 말 것.** 여기엔 face level 1이 있는데 입력 연산이 거의 0이라
   cold-start/OpenCV 초기화가 지배해 solo가 **2852ms로 튄다**(level 5의 472ms보다 큼). 반드시
   `reexp_input_variance`(face lv5~30 + float lv1M~12M)를 쓴다. baseline(cloudwatch/kpa)도 같은 데이터.

3. **overhead 측정 — 32MB ring buffer로 빌드.** `overhead_resource`의 RSS와 `overhead_e2e`/`overhead_nodeload`는
   `src/puretime.bpf.c`의 ring buffer를 **32MB**로 빌드해 측정한다(plot의 `RING_BUFFER_MB=32`와 일치).
   512MB 빌드면 libbpf 이중매핑으로 RSS≈1GB가 되어 어긋난다. **측정 후 반드시 512MB로 복원**한다.
   - `overhead_resource.csv`의 `resource_type` 열은 **victim명 7종**(float_op…compression)이어야 한다.
     옛 `cpu/network/block_io` 3종이면 plot(7 victim)과 안 맞아 빈 figure가 나온다.
   - `overhead_e2e`는 loader를 victim 코어에 cpulimit-pin해 critical-path 오버헤드를 측정하고,
     순수 I/O victim(uploader/compression)은 512MB ring buffer로 net/block softirq 경합을 반영한다.

4. **block 측정(compression, robustness의 bio) — 디스크 전제 2가지.** `queue_depth=2` + **filled/fragmented HDD**.
   빈 디스크는 contiguous fast-track이라 removal이 91%→45%로 무너진다. `/mnt/hdd`의 bulk 파일을 지우지 말 것.
   (CLAUDE.md "Pre-requirements for valid measurement" 참조.)

5. **net 측정(uploader/s3) — MinIO + NIC offload off.** `uploads` 버킷 존재, `ethtool -K <iface> tso off gso off
   gro off lro off`. 네트워크 귀속은 TCP-TX only.

## 데이터 측정 스크립트(참고)

| 데이터 | 측정 스크립트 |
|---|---|
| `accuracy_7victim/`, `accuracy_K50/` | `exp_accuracy_by_type.sh` |
| `robustness_1b/` | (accuracy sweep의 강도 변형) |
| `mixed_noise/` | `exp_mixed_noise.sh` |
| `reexp_input_variance/` | `exp_input_variance.sh` |
| `overhead/overhead_resource.csv` | `exp_overhead_resource.sh` (32MB 빌드) |
| `overhead_e2e/` | `exp_overhead_e2e.sh` (32MB 빌드) |
| `overhead_nodeload/` | `exp_overhead_nodeload.sh` |
