#!/usr/bin/env python3
"""
Figure 1 — PureTime pipeline  (SoCC 2026)
스케치(figures/sketch.png) 충실 재현: 4단계, 전부 시간축 t 위의 interval 도출.
  01 DETECT  : 커널 4자원 큐 + eBPF hook point
  02 EXTRACT : self/other 매칭 → wait(빨강 해치) 추출
  03 MERGE   : 자원별 wait 를 union → W_merged
  04 RECOVER : Wall − W_merged = T_pure (파랑)

색: wait=red 해치, pure=blue 해치, self=ink span, other=gray span, wall=ink outline.
출력: figures/fig1_architecture.{pdf,png}
"""
import os
import numpy as np
import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrowPatch, FancyBboxPatch, Polygon

# ── tokens ───────────────────────────────────────────────────────────────────
INK    = "#13293d"
WAIT   = "#c0392b"; WAIT_S = "#f6d8d1"
PURE   = "#1d6fb8"; PURE_S = "#d3e6f5"
OTHER  = "#8a97a6"   # other span outline (muted)
RAIL   = "#cdd8e3"
MUTE   = "#6b7c8c"
PAPER  = "#f8fafb"

SANS = "DejaVu Sans"
MONO = "DejaVu Sans Mono"

mpl.rcParams.update({
    "font.family": SANS, "axes.unicode_minus": False,
    "pdf.fonttype": 42, "ps.fonttype": 42,
    "hatch.linewidth": 0.6,
})

fig, ax = plt.subplots(figsize=(13.6, 7.0))
fig.patch.set_facecolor(PAPER); ax.set_facecolor(PAPER)
ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")

# ── panel geometry ───────────────────────────────────────────────────────────
ML, MR = 1.2, 1.2
WC = 5.6
WP = (100 - ML - MR - 3*WC) / 4
PAN = []
x = ML
for i in range(4):
    PAN.append((x, x+WP)); x += WP + WC
PBODY = (9, 80)            # panel body y-range
TITLE_Y = 88

# ── small helpers ─────────────────────────────────────────────────────────────
def taxis(x0, x1, y, lab=True):
    ax.annotate("", xy=(x1+0.4, y), xytext=(x0, y),
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.0), zorder=3)
    if lab:
        ax.text(x1+0.9, y-0.4, "t", family=MONO, fontsize=6.5, style="italic",
                color=INK, ha="left", va="top", zorder=3)

def span(x0, x1, y, ec, h=2.0, lw=1.1):
    ax.add_patch(Rectangle((x0, y-h/2), x1-x0, h, facecolor="white",
                 edgecolor=ec, lw=lw, zorder=4))

def hbar(x0, x1, y, color, soft, h=2.2):
    ax.add_patch(Rectangle((x0, y-h/2), x1-x0, h, facecolor=soft, edgecolor=color,
                 lw=1.0, hatch="////", zorder=4))

def vtick(x, y, h, color=INK, lw=1.0):
    ax.plot([x, x], [y-h/2, y+h/2], color=color, lw=lw, zorder=5)

def chevron(xc, y):
    ax.annotate("", xy=(xc, y-2.6), xytext=(xc, y+2.6),
                arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.6), zorder=5)

def panel_frame(i, accent=False):
    x0, x1 = PAN[i]
    ax.add_patch(FancyBboxPatch((x0, PBODY[0]), x1-x0, PBODY[1]-PBODY[0],
                 boxstyle="round,pad=0,rounding_size=1.0", facecolor="white",
                 edgecolor=(PURE if accent else RAIL),
                 lw=(1.8 if accent else 1.0), zorder=2))

def header(i, num, verb, sub, accent=False):
    x0, x1 = PAN[i]
    acc = PURE if accent else INK
    ax.text(x0+1.2, TITLE_Y+3.4, verb, family=MONO, fontsize=6.4,
            color=(PURE if accent else MUTE), ha="left", va="center", zorder=4)
    ax.text(x0+1.2, TITLE_Y-1.0, num, family=MONO, fontsize=15, fontweight="bold",
            color=acc, ha="left", va="center", zorder=4)
    ax.text(x0+7.0, TITLE_Y-1.0, sub, family=SANS, fontsize=8.2, fontweight="bold",
            color=INK, ha="left", va="center", zorder=4)

def connector(i, label):
    x0 = PAN[i][1]; x1 = PAN[i+1][0]; yc = (PBODY[0]+PBODY[1])/2
    tri = Polygon([(x0+1.0, yc+2.4), (x0+1.0, yc-2.4), (x1-1.0, yc)],
                  closed=True, facecolor="white", edgecolor=INK, lw=1.2, zorder=4)
    ax.add_patch(tri)
    fam = MONO if "$" not in label else SANS
    ax.text((x0+x1)/2, yc+4.0, label, family=fam, fontsize=6.0, color=INK,
            ha="center", va="bottom", zorder=4)

# ══════════════════════════════════════════════════════════════════════════════
# 01 DETECT — 커널 4자원 큐 + eBPF hook
# ══════════════════════════════════════════════════════════════════════════════
def p_detect(i):
    x0, x1 = PAN[i]
    ix0, ix1 = x0+3.2, x1-2.0
    rows = [
        ("Run queue",        [("proc", False), ("?", False)]),
        ("Network TX queue", [("pkt", False)]),
        ("Block I/O queue",  [("bio", False)]),
        ("softirq window",   None),               # window: no queued items
    ]
    ys = np.linspace(PBODY[1]-9, PBODY[0]+8, 4)
    qh = 6.0
    for y, (name, items) in zip(ys, rows):
        is_win = items is None
        ax.text(ix0, y+qh/2+1.4, name, family=MONO, fontsize=6.0, color=INK,
                ha="left", va="bottom", zorder=5)
        ax.add_patch(Rectangle((ix0, y-qh/2), ix1-ix0, qh, facecolor="white",
                     edgecolor=INK, lw=1.1, ls=("--" if is_win else "-"), zorder=3))
        # hook points (eBPF) at both ends — ink(구조색)으로: red는 wait 전용
        for hx in (ix0, ix1):
            ax.plot([hx], [y], marker="D", ms=5.2, color=INK,
                    markeredgecolor="white", mew=0.6, zorder=6)
        # queued items
        if items:
            n = len(items); slot = (ix1-ix0)/2.6
            sx = ix1 - 0.8 - n*slot
            for k, (lab, _) in enumerate(items):
                rx = sx + k*slot
                ax.add_patch(Rectangle((rx, y-qh/2+1.3), slot-0.8, qh-2.6,
                             facecolor="#eef3f7", edgecolor=INK, lw=0.8, zorder=4))
                ax.text(rx+(slot-0.8)/2, y, lab, family=MONO, fontsize=5.4,
                        color=INK, ha="center", va="center", zorder=5)

# ══════════════════════════════════════════════════════════════════════════════
# 02 EXTRACT — self/other 매칭 → wait 추출
# ══════════════════════════════════════════════════════════════════════════════
def p_extract(i):
    x0, x1 = PAN[i]
    ix0, ix1 = x0+5.0, x1-2.5
    sp = ix1 - ix0
    def at(f): return ix0 + sp*f
    # ── step A: self/other spans + service point ──
    y_self, y_oth, axA = 67, 60, 54
    taxis(ix0, ix1, axA)
    span(at(.30), at(.92), y_self, INK)
    span(at(.10), at(.58), y_oth, OTHER)
    vtick(at(.30), y_self, 2.4, INK); vtick(at(.92), y_self, 2.4, INK)
    vtick(at(.10), y_oth, 2.4, OTHER); vtick(at(.58), y_oth, 2.4, OTHER)
    ax.text(x0+1.0, y_self, "self",  family=MONO, fontsize=6.0, color=INK,  fontweight="bold", ha="left", va="center", zorder=5)
    ax.text(x0+1.0, y_oth,  "other", family=MONO, fontsize=6.0, color=OTHER, fontweight="bold", ha="left", va="center", zorder=5)
    ax.text(at(.30), y_self+2.2, "enq", family=MONO, fontsize=4.8, color=MUTE, ha="center", va="bottom", zorder=5)
    ax.text(at(.92), y_self+2.2, "deq", family=MONO, fontsize=4.8, color=MUTE, ha="center", va="bottom", zorder=5)
    # service point: other dequeued (serviced) inside self's pending window → red dashed
    ax.plot([at(.58), at(.58)], [y_oth-3.5, y_self+3.5], color=WAIT, lw=0.9, ls=(0,(3,2)), zorder=5)
    ax.text(at(.58), y_self+4.2, "other serviced", family=MONO, fontsize=4.8,
            color=WAIT, ha="center", va="bottom", zorder=6)
    # ── chevron ──
    chevron((ix0+ix1)/2, 45)
    # ── step B: extracted wait inside self's span ──
    yB, axB = 32, 26
    taxis(ix0, ix1, axB)
    span(at(.30), at(.92), yB, INK)
    hbar(at(.58), at(.92), yB, WAIT, WAIT_S)       # wait = other-serviced .. self deq
    ax.plot([at(.58), at(.58)], [yB-5, yB+4], color=WAIT, lw=0.9, ls=(0,(3,2)), zorder=5)
    ax.text(at(.75), yB+2.4, "wait", family=MONO, fontsize=5.4, color=WAIT,
            fontweight="bold", ha="center", va="bottom", zorder=6)
    ax.text(x0+1.0, yB, "self", family=MONO, fontsize=6.0, color=INK, fontweight="bold", ha="left", va="center", zorder=5)

# ══════════════════════════════════════════════════════════════════════════════
# 03 MERGE — 자원별 wait 를 union
# ══════════════════════════════════════════════════════════════════════════════
def p_merge(i):
    x0, x1 = PAN[i]
    ix0, ix1 = x0+6.0, x1-2.5
    sp = ix1-ix0
    def at(f): return ix0+sp*f
    cpu_w = [(.12,.30), (.55,.78)]
    net_w = [(.20,.40), (.62,.92)]
    # ── step A: per-resource waits on aligned t ──
    y_cpu, y_net, axA = 67, 59, 53
    taxis(ix0, ix1, axA)
    for a,b in cpu_w: hbar(at(a), at(b), y_cpu, WAIT, WAIT_S)
    for a,b in net_w: hbar(at(a), at(b), y_net, WAIT, WAIT_S)
    ax.text(x0+1.0, y_cpu, "CPU", family=MONO, fontsize=6.0, color=INK, fontweight="bold", ha="left", va="center", zorder=5)
    ax.text(x0+1.0, y_net, "NET", family=MONO, fontsize=6.0, color=INK, fontweight="bold", ha="left", va="center", zorder=5)
    # ── chevron ──
    chevron((ix0+ix1)/2, 44)
    # ── step B: merged union ──
    yB = 31
    taxis(ix0, ix1, yB-6)
    # union of cpu_w ∪ net_w
    ivs = sorted(cpu_w+net_w)
    merged=[]; cs,ce=ivs[0]
    for a,b in ivs[1:]:
        if a<=ce: ce=max(ce,b)
        else: merged.append((cs,ce)); cs,ce=a,b
    merged.append((cs,ce))
    for a,b in merged: hbar(at(a), at(b), yB, WAIT, WAIT_S)
    ax.text(x0+1.0, yB, "merged", family=MONO, fontsize=5.6, color=WAIT, fontweight="bold", ha="left", va="center", zorder=5)
    # overlap-collapse 주석
    ax.text(at(.65), yB+2.6, "overlap → counted once", family=MONO, fontsize=4.6,
            color=WAIT, ha="center", va="bottom", zorder=6)

# ══════════════════════════════════════════════════════════════════════════════
# 04 RECOVER — Wall − W_merged = T_pure  (signature)
# ══════════════════════════════════════════════════════════════════════════════
def p_recover(i):
    x0, x1 = PAN[i]
    ix0, ix1 = x0+6.0, x1-2.5
    sp = ix1-ix0
    def at(f): return ix0+sp*f
    merged_w = [(.10,.22), (.55,.78)]              # 노이즈 ~0.35 → pure 다수
    # ── step A: wall bar + merged waits ──
    y_wall, y_w, axA = 67, 59, 53
    taxis(ix0, ix1, axA)
    span(ix0, ix1, y_wall, INK, h=2.4)
    for a,b in merged_w: hbar(at(a), at(b), y_w, WAIT, WAIT_S)
    ax.text(x0+1.0, y_wall, "wall",  family=MONO, fontsize=5.8, color=INK,  fontweight="bold", ha="left", va="center", zorder=5)
    ax.text(x0+1.0, y_w, "merged", family=MONO, fontsize=5.2, color=WAIT, fontweight="bold", ha="left", va="center", zorder=5)
    # ── chevron ──
    chevron((ix0+ix1)/2, 44)
    # ── step B: aligned decomposition  wall = pure + Σwait ──
    axB = 18
    taxis(ix0, ix1, axB)
    Wtot = sum(b-a for a,b in merged_w)            # 총 노이즈 길이(비율)
    split = 1 - Wtot                                # pure 비율
    yW, yP, yS = 37, 31, 25
    span(ix0, ix1, yW, INK, h=2.4)                              # wall
    hbar(ix0, at(split), yP, PURE, PURE_S, h=2.4)              # pure (파랑)
    hbar(at(split), ix1, yS, WAIT, WAIT_S, h=2.4)             # Σ wait (빨강, 우측)
    ax.plot([at(split), at(split)], [axB-1, yW+2.5], color=MUTE, lw=0.7, ls=(0,(2,2)), zorder=3)
    ax.plot([ix1, ix1], [axB-1, yW+2.5], color=MUTE, lw=0.7, ls=(0,(2,2)), zorder=3)
    ax.text(x0+1.0, yW, "wall", family=MONO, fontsize=5.8, color=INK,  fontweight="bold", ha="left", va="center", zorder=5)
    ax.text(x0+1.0, yP, "pure", family=MONO, fontsize=5.8, color=PURE, fontweight="bold", ha="left", va="center", zorder=5)
    ax.text(x0+1.0, yS, "Σwait",family=MONO, fontsize=5.2, color=WAIT, fontweight="bold", ha="left", va="center", zorder=5)
    # 결과 식
    ax.text((ix0+ix1)/2, 10.5,
            r"$T_{\mathrm{wall}}-W_{\mathrm{merged}}=T_{\mathrm{pure}}$",
            fontsize=8.0, color=INK, ha="center", va="bottom", zorder=6)

# ── build ─────────────────────────────────────────────────────────────────────
panel_frame(0); panel_frame(1); panel_frame(2); panel_frame(3, accent=True)
header(0, "01", "DETECT",  "Kernel event hooks")
header(1, "02", "EXTRACT", "Owner + wait time")
header(2, "03", "MERGE",   "Union across resources")
header(3, "04", "RECOVER", "Pure time", accent=True)
p_detect(0); p_extract(1); p_merge(2); p_recover(3)
connector(0, "detected events")
connector(1, "per-resource waits")
connector(2, r"$W_{\mathrm{merged}}$")

# ── legend strip ──────────────────────────────────────────────────────────────
ly = 3.5
def leg_patch(x, kind):
    if kind == "hook":
        ax.plot([x], [ly], marker="D", ms=5.0, color=INK, markeredgecolor="white", mew=0.6)
    elif kind == "self":
        ax.add_patch(Rectangle((x-1.4, ly-1.0), 2.8, 2.0, facecolor="white", edgecolor=INK, lw=1.0))
    elif kind == "other":
        ax.add_patch(Rectangle((x-1.4, ly-1.0), 2.8, 2.0, facecolor="white", edgecolor=OTHER, lw=1.0))
    elif kind == "wait":
        ax.add_patch(Rectangle((x-1.4, ly-1.0), 2.8, 2.0, facecolor=WAIT_S, edgecolor=WAIT, lw=1.0, hatch="////"))
    elif kind == "pure":
        ax.add_patch(Rectangle((x-1.4, ly-1.0), 2.8, 2.0, facecolor=PURE_S, edgecolor=PURE, lw=1.0, hatch="////"))
items = [("hook","eBPF hook point"), ("self","self span"), ("other","other span"),
         ("wait","wait (removed)"), ("pure","pure time")]
lx = 9
for kind, lab in items:
    leg_patch(lx, kind)
    ax.text(lx+2.6, ly, lab, family=SANS, fontsize=6.2, color=INK, ha="left", va="center")
    lx += 2.6 + len(lab)*1.05 + 4.5

plt.subplots_adjust(left=0.004, right=0.996, top=0.995, bottom=0.005)
outdir = os.path.dirname(__file__) + "/figures"
fig.savefig(outdir+"/fig1_architecture.pdf", facecolor=PAPER)
fig.savefig(outdir+"/fig1_architecture.png", dpi=200, facecolor=PAPER)
print("saved fig1_architecture.{pdf,png}")
