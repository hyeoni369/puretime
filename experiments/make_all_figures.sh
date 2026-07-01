#!/usr/bin/env bash
# =============================================================================
# 논문(sigconf.tex) figure 전체 재생성 — 데이터가 있을 때 plot만 실행.
# (데이터 *측정* 자체는 exp_*.sh; 측정 주의사항은 docs/figures-reproduction.md 참조)
#
# 데이터-기반 figure 10종 ↔ 스크립트 ↔ 데이터 매핑은 아래 각 커맨드 주석 참고.
# 수동/외부 그림(architecture, wait-model-a/b, merge, trace_for_cv, teaser)은 제외.
#
# 사용법: bash experiments/make_all_figures.sh [출력디렉토리(기본 figures)]
# =============================================================================
set -e
cd "$(dirname "$0")"
OUT="${1:-figures}"; D=data
mkdir -p "$OUT"

# 1) accuracy_normalized — 정확도(7 victim, solo=1 정규화). self-contained(--out 없음, figures/에 저장).
#    데이터: data/accuracy_7victim/{cpu_float,cpu_factors,cpu_sequential,cpu_aes,net_uploader,net_s3}.csv
#            + data/accuracy_K50/results.csv(block_io=compression).
#    removal·bar 모두 pairwise(각 noisy를 같은 iteration의 solo로 정규화 → HDD drift 보정).
python3 plot_accuracy_normalized.py

# 2) robustness — 경합 강도 sweep(CPU+Net; block은 disk-state 의존이라 제외).
#    데이터: --acc data/accuracy_K50/accuracy_results.csv(CPU) --net data/robustness_1b/results.csv(Net)
python3 plot_exp1b_robustness.py --acc "$D/accuracy_K50/accuracy_results.csv" --net "$D/robustness_1b/results.csv" --out "$OUT"

# 3) interval_merge_scatter — interval-merge ablation(동시 CPU+Net victim, 겹치는 wait).
#    데이터: data/mixed_noise/results.csv
python3 plot_exp2_interval_merge.py --data "$D/mixed_noise/results.csv" --out "$OUT"

# 4) input_variance_face + input_variance_float — 입력 변화 대비 PureTime 복원(solo 추종).
#    데이터: data/reexp_input_variance/results.csv (face lv5~30 + float lv1M~12M).
#    ※ data/reexp_iv_face(face lv1 포함)는 lv1이 cold-start/OpenCV 초기화로 solo가 튀어(2852ms) 제외.
python3 plot_exp3_input_variance.py --data "$D/reexp_input_variance/results.csv" --out "$OUT"

# 5) baseline_cloudwatch_2band + baseline_kpa — CloudWatch/KPA 반사실 비교.
#    데이터: exp3와 동일(data/reexp_input_variance/results.csv), --victim face.
python3 plot_exp4_baseline.py --data "$D/reexp_input_variance/results.csv" --victim face --out "$OUT"

# 6) overhead_resource — PureTime loader의 노드 자원(CPU%/RSS), 7 victim.
#    데이터: data/overhead/overhead_resource.csv (resource_type=victim명 7종; 옛 cpu/network/block 3종 아님).
#    ※ RSS는 32MB ring buffer 빌드 기준(plot RING_BUFFER_MB=32). 512MB 빌드면 RSS≈1GB로 어긋남.
python3 plot_overhead_resource.py --data "$D/overhead/overhead_resource.csv" --out "$OUT"

# 7) overhead_e2e — PureTime ON/OFF 실행시간 오버헤드, 7 victim(경합환경 <2% 양수).
#    데이터: data/overhead_e2e/results.csv
python3 plot_overhead_e2e.py --data "$D/overhead_e2e/results.csv" --out "$OUT"

# 8) overhead_nodeload — 노드 부하 대비 per-function 오버헤드 flat.
#    데이터: data/overhead_nodeload/results.csv
python3 plot_overhead_nodeload.py --data "$D/overhead_nodeload/results.csv" --out "$OUT"

echo "=== 생성된 figures ==="; ls "$OUT"/*.pdf
