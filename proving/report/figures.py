"""Small hand-written SVG figures: a reliability diagram per judge and an error-correlation grid.

Plain SVG keeps the figures diffable in git and needs no plotting library in CI.
"""

from __future__ import annotations

INK, MUTED, GRID, ACCENT, WARM = "#1f2328", "#6e7781", "#d0d7de", "#0969da", "#bc4c00"


def _svg(w: int, h: int, body: list[str]) -> str:
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'font-family="system-ui, sans-serif" font-size="12">')
    return "\n".join([head, f'<rect width="{w}" height="{h}" fill="#ffffff"/>', *body, "</svg>"]) + "\n"


def reliability(per_judge: dict) -> str:
    size, pad, gap = 180, 36, 30
    names = list(per_judge)
    w = pad + len(names) * (size + gap)
    h = size + pad * 2 + 20
    body = []
    for i, name in enumerate(names):
        j = per_judge[name]
        x0, y0 = pad + i * (size + gap), pad
        body.append(f'<text x="{x0}" y="{y0 - 12}" fill="{INK}" font-weight="600">{name}</text>')
        body.append(f'<rect x="{x0}" y="{y0}" width="{size}" height="{size}" fill="none" stroke="{GRID}"/>')
        body.append(f'<line x1="{x0}" y1="{y0 + size}" x2="{x0 + size}" y2="{y0}" stroke="{GRID}" '
                    f'stroke-dasharray="4 3"/>')
        for key, colour in (("reliability_raw", WARM), ("reliability_calibrated", ACCENT)):
            pts = [(x0 + b["confidence"] * size, y0 + size - b["accuracy"] * size) for b in j[key]]
            if pts:
                body.append(f'<polyline fill="none" stroke="{colour}" stroke-width="2" points="'
                            + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + '"/>')
                body += [f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{colour}"/>' for x, y in pts]
        body.append(f'<text x="{x0}" y="{y0 + size + 16}" fill="{MUTED}">ECE raw {j["ece_raw"]}, '
                    f'calibrated {j["ece_calibrated"]}</text>')
    body.append(f'<text x="{pad}" y="{h - 8}" fill="{MUTED}">x: stated confidence, y: share that was right. '
                f'Orange raw, blue after calibration on anchors, dashed line perfect.</text>')
    return _svg(w, h, body)


def correlation(corr: dict) -> str:
    names = corr["judges"]
    cell, pad = 70, 110
    w = pad + cell * len(names) + 20
    h = pad + cell * len(names) + 40
    body = []
    for i, a in enumerate(names):
        body.append(f'<text x="{pad - 8}" y="{pad + i * cell + cell / 2 + 4}" text-anchor="end" fill="{INK}">{a}</text>')
        body.append(f'<text x="{pad + i * cell + cell / 2}" y="{pad - 10}" text-anchor="middle" fill="{INK}">{a}</text>')
        for j, b in enumerate(names):
            if a == b:
                value = 1.0
            else:
                value = corr["pairwise"].get(f"{a}|{b}", corr["pairwise"].get(f"{b}|{a}"))
            shade = 0 if value is None else max(0.0, min(1.0, value))
            fill = f"rgba(9,105,218,{0.12 + 0.75 * shade:.2f})"
            label = "n/a" if value is None else f"{value:.2f}"
            x, y = pad + j * cell, pad + i * cell
            body.append(f'<rect x="{x}" y="{y}" width="{cell - 2}" height="{cell - 2}" fill="{fill}"/>')
            body.append(f'<text x="{x + cell / 2}" y="{y + cell / 2 + 4}" text-anchor="middle" fill="{INK}">{label}</text>')
    body.append(f'<text x="12" y="{h - 14}" fill="{MUTED}">Correlation of judge errors on held-out calls. '
                f'Mean {corr["mean_error_correlation"]}, effective independent judges {corr["effective_judges"]} '
                f'of {len(names)}.</text>')
    return _svg(w, h, body)
