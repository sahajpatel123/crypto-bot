"""Inline SVG charts (V-007). Zero JavaScript, zero CDN: pure static SVG."""
from __future__ import annotations

W, H, PAD_L, PAD_B, PAD_T, PAD_R = 640, 220, 64, 34, 14, 14
INK, GRID, UP, DOWN, MUTED = "#1a1a1a", "#d8d8d8", "#0a6b3a", "#b00020", "#6b6b6b"


def _frame(title: str, caption: str, body: str, max_v: float, min_v: float,
           y_fmt) -> str:
    pw, ph = W - PAD_L - PAD_R, H - PAD_T - PAD_B
    lines = []
    for i in range(5):
        v = min_v + (max_v - min_v) * i / 4 if max_v != min_v else min_v
        y = PAD_T + ph - ph * i / 4
        lines.append(
            f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
            f'<text x="{PAD_L - 6}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-size="10" fill="{MUTED}">{y_fmt(v)}</text>')
    return (
        f'<figure role="img" aria-label="{title}">'
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="system-ui,-apple-system,Segoe UI,sans-serif">'
        f'<text x="{PAD_L}" y="12" font-size="12" font-weight="600" fill="{INK}">'
        f'{title}</text>{"".join(lines)}{body}</svg>'
        f'<figcaption>{caption}</figcaption></figure>')


def _x(i: int, n: int) -> float:
    pw = W - PAD_L - PAD_R
    return PAD_L if n <= 1 else PAD_L + pw * i / (n - 1)


def _y(v: float, lo: float, hi: float) -> float:
    ph = H - PAD_T - PAD_B
    if hi == lo:
        return PAD_T + ph / 2
    return PAD_T + ph - ph * (v - lo) / (hi - lo)


def line_chart(title: str, caption: str, values: list[float],
               fmt=lambda v: f"{v:,.0f}") -> str:
    if not values:
        return _frame(title, caption + " — no data",
                      f'<text x="{W/2}" y="{H/2}" text-anchor="middle" font-size="12" '
                      f'fill="{MUTED}">no data</text>', 1, 0, fmt)
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.05 or 1.0
    lo, hi = lo - pad, hi + pad
    pts = " ".join(f"{_x(i, len(values)):.1f},{_y(v, lo, hi):.1f}"
                   for i, v in enumerate(values))
    body = (f'<polyline points="{pts}" fill="none" stroke="{INK}" '
            f'stroke-width="1.5"/>')
    return _frame(title, caption, body, hi, lo, fmt)


def drawdown_chart(title: str, caption: str, drawdowns: list[float]) -> str:
    if not drawdowns:
        return line_chart(title, caption, [], lambda v: f"{v:,.0f}")
    lo, hi = min(0.0, min(drawdowns)), max(0.0, max(drawdowns))
    n = len(drawdowns)
    pts = " ".join(f"{_x(i, n):.1f},{_y(v, lo, hi):.1f}"
                   for i, v in enumerate(drawdowns))
    base = _y(0.0, lo, hi)
    first_x, last_x = _x(0, n), _x(n - 1, n)
    body = (f'<polygon points="{first_x:.1f},{base:.1f} {pts} {last_x:.1f},{base:.1f}" '
            f'fill="{DOWN}" opacity="0.18"/>'
            f'<polyline points="{pts}" fill="none" stroke="{DOWN}" stroke-width="1.5"/>')
    return _frame(title, caption, body, hi, lo, lambda v: f"{v:,.0f}")


def bar_chart(title: str, caption: str, labels: list[str], values: list[float],
              fmt=lambda v: f"{v:+.2%}") -> str:
    if not values:
        return line_chart(title, caption, [], fmt)
    lo, hi = min(0.0, min(values)), max(0.0, max(values))
    if hi == lo:
        hi = lo + 1.0
    n = len(values)
    pw = W - PAD_L - PAD_R
    slot = pw / n
    bw = max(2.0, min(40.0, slot * 0.6))
    bars = []
    base = _y(0.0, lo, hi)
    for i, v in enumerate(values):
        cx = _x(i, n)
        yv = _y(v, lo, hi)
        top, h = (yv, base - yv) if v >= 0 else (base, yv - base)
        color = UP if v >= 0 else DOWN
        bars.append(f'<rect x="{cx - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" '
                    f'height="{max(h, 1.0):.1f}" fill="{color}"/>')
        if n <= 16:
            bars.append(f'<text x="{cx:.1f}" y="{H - 8}" text-anchor="middle" '
                        f'font-size="9" fill="{MUTED}">{labels[i]}</text>')
    return _frame(title, caption, "".join(bars), hi, lo, fmt)


def strategy_chart(title: str, caption: str, names: list[str],
                   nets: list[float]) -> str:
    return bar_chart(title, caption, names, nets, lambda v: f"{v:+,.0f}")
