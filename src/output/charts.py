"""Lightweight SVG charts without matplotlib."""

from __future__ import annotations


def price_history_svg(points: list[tuple[str, float]], title: str = "Price history") -> str:
    """Return an inline SVG line chart for a list of (label, price) points."""
    if not points or len(points) < 2:
        return ""
    prices = [p for _, p in points]
    lo, hi = min(prices), max(prices)
    if hi == lo:
        hi = lo + 1
    w, h = 400, 160
    pad = 30
    xs = [pad + i * (w - 2 * pad) / (len(points) - 1) for i in range(len(points))]
    ys = [h - pad - (p - lo) / (hi - lo) * (h - 2 * pad) for p in prices]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    labels = "".join(
        f'<text x="{x:.1f}" y="{h-5}" font-size="9" text-anchor="middle">{lab[:8]}</text>'
        for x, lab in zip(xs, [p[0] for p in points])
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}">\n'
        f'  <text x="{w/2}" y="14" font-size="12" text-anchor="middle">{title}</text>\n'
        f'  <polyline points="{poly}" fill="none" stroke="#2563eb" stroke-width="2"/>\n'
        f'  {labels}\n'
        f'  <text x="5" y="{pad}" font-size="9">{hi:.0f}</text>\n'
        f'  <text x="5" y="{h-pad}" font-size="9">{lo:.0f}</text>\n'
        f'</svg>'
    )
"