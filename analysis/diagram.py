"""System architecture figure for the report.

    python -m analysis.diagram            # writes report/figures/architecture.png
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

BLUE, ORANGE, GREEN, GREY, INK = "#dbe7fb", "#fde4cf", "#d8efdf", "#ececec", "#222222"


def box(ax, x, y, w, h, title, body, color):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc=color, ec=INK, lw=0.8))
    ax.text(x + w / 2, y + h - 0.16, title, ha="center", va="top", fontsize=8.5, weight="bold", color=INK)
    ax.text(x + w / 2, y + h - 0.45, body, ha="center", va="top", fontsize=6.6, color=INK, linespacing=1.35)


def arrow(ax, a, b, label="", rad=0.0, lx=0.0, ly=0.0, dashed=False):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=9, lw=0.9, color=INK,
                                 connectionstyle=f"arc3,rad={rad}", ls="--" if dashed else "-"))
    if label:
        mx, my = (a[0] + b[0]) / 2 + lx, (a[1] + b[1]) / 2 + ly
        ax.text(mx, my, label, fontsize=6.4, ha="center", va="center", color=INK,
                bbox=dict(fc="white", ec="none", pad=0.6))


def main(out: Path = Path("report/figures/architecture.png")) -> None:
    fig, ax = plt.subplots(figsize=(9.5, 5.0))
    ax.set_xlim(0, 10); ax.set_ylim(0, 5.4); ax.axis("off")

    box(ax, 0.2, 2.0, 2.6, 1.9, "Trader agents (x10)",
        "5 buyers, 5 sellers\nprivate unit values / costs\npersona + memory of past periods\n"
        "output: action, price,\nbelief, (chat), reasoning", BLUE)
    box(ax, 3.9, 3.5, 2.4, 1.6, "Message bus",
        "channels:\nbeliefs  (trader -> analyst)\nanalyst  (analyst -> traders)\nchat  (trader <-> trader, optional)", GREY)
    box(ax, 7.3, 3.5, 2.5, 1.6, "Analyst agent",
        "aggregates disagreeing beliefs\n+ recent trade prices\n-> consensus estimate + spread\n(rule-based or LLM)", ORANGE)
    box(ax, 3.9, 0.5, 2.4, 1.8, "Auctioneer + order book",
        "continuous double auction\nrandom arrival order each round\nbudget constraint enforced\n"
        "trades at standing price", GREEN)
    box(ax, 7.3, 0.5, 2.5, 1.8, "Evaluation",
        "competitive equilibrium (ground truth)\nefficiency, price RMSD, Smith's alpha\nsurplus split, clip / error rates\n"
        "vs ZI-C, ZI-U, oracle,\ncentralized LLM", GREY)
    box(ax, 0.2, 0.2, 2.6, 1.25, "LLM client",
        "Ollama (local) | Claude API | mock\nJSON-schema output, cache,\ntoken + cost accounting", GREY)

    arrow(ax, (2.8, 3.6), (3.9, 4.2), "beliefs, chat", ly=0.12)
    arrow(ax, (7.3, 4.3), (6.3, 4.3), "estimate", ly=0.13)
    arrow(ax, (6.3, 3.9), (7.3, 3.9), "beliefs", ly=-0.13)
    arrow(ax, (3.9, 3.75), (2.8, 3.25), "broadcasts", ly=-0.15)
    arrow(ax, (2.8, 2.35), (3.9, 1.7), "orders", ly=-0.05, lx=-0.1)
    arrow(ax, (3.9, 1.1), (2.8, 2.05), "book + trade tape", rad=-0.25, lx=0.2, ly=-0.3)
    arrow(ax, (6.3, 1.4), (7.3, 1.4), "trade log", ly=0.13)
    arrow(ax, (8.55, 3.5), (8.55, 2.3), "analyst log", lx=0.0, dashed=True)
    arrow(ax, (1.5, 1.45), (1.5, 2.0), "", dashed=True)
    ax.text(1.62, 1.72, "decide()", fontsize=6.4, color=INK)

    ax.text(5.0, 5.3, "One round: all traders decide in parallel on the same snapshot -> beliefs posted -> orders "
            "matched in random order -> analyst broadcasts", ha="center", fontsize=7, style="italic", color="#555555")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(); fig.savefig(out, dpi=170); plt.close(fig)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
