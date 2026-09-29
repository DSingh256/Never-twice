"""Build the article's image set into content/images/.

Three pieces are rendered from styled HTML (hero, architecture, terminal) —
the terminal one embeds REAL captured API output, never invented text.
Everything else is copied verbatim from render/frames/, the live-app
screenshots staged for the video render (they are the honest artifact).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "scripts" / "assets" / "article"
FRAMES = ROOT / "render" / "frames"
OUT = ROOT / "content" / "images"

# generated pieces: (html file, output png, viewport)
GENERATED = [
    ("hero.html", "hero-cover.png", (1200, 630)),
    ("architecture.html", "architecture.png", (1400, 1000)),
    ("terminal.html", "terminal-memory.png", (1280, 760)),
]

# real app frames copied into the article set: (frame file, article name)
COPIED = [
    ("s2_exhibit.png", "tribunal-exhibit.png"),
    ("s3_witness_a.png", "witness-a-naked.png"),
    ("s4_witness_b.png", "witness-b-memory.png"),
    ("s7_tribunal_full.png", "tribunal-full.png"),
    ("s7b_delta_panel.png", "delta-panel.png"),
    ("s4b_atlas_failed_fixes.png", "atlas-failed-fixes.png"),
    ("s5_learning_lab.png", "learning-lab.png"),
    ("s6_eval.png", "eval-table.png"),
]


def render_generated() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for html, png, (w, h) in GENERATED:
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto((ASSETS / html).as_uri())
            page.wait_for_timeout(300)
            page.screenshot(path=str(OUT / png))
            page.close()
            print(f"rendered {png}")
        browser.close()


def copy_frames() -> None:
    for src, dst in COPIED:
        src_path = FRAMES / src
        if not src_path.is_file():
            print(f"WARNING: frame missing, skipped: {src}")
            continue
        shutil.copyfile(src_path, OUT / dst)
        print(f"copied {dst}")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    copy_frames()
    render_generated()
    print(f"done -> {OUT}")
