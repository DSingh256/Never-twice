"""Build the LinkedIn-article image set into content/images/linkedin/.

LinkedIn's article editor has no markdown, tables, or code blocks — so the
two Python excerpts become styled code-card images (same archive-night look
as the terminal card), and everything else reuses content/images/ verbatim.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "scripts" / "assets" / "article"
OUT = ROOT / "content" / "images" / "linkedin"

# code excerpts -> code-card images
CODE_CARDS = [
    ("code_leakcheck.html", "code-leakcheck.png"),
    ("code_retain.html", "code-retain.png"),
]

# images already used by the article that the LinkedIn version reuses
ARTICLE_IMAGES = ROOT / "content" / "images"
REUSE = [
    ("hero-cover.png", "hero-cover.png"),
    ("architecture.png", "architecture.png"),
    ("terminal-memory.png", "terminal-memory.png"),
    ("witness-a-naked.png", "witness-a-naked.png"),
    ("witness-b-memory.png", "witness-b-memory.png"),
    ("learning-lab.png", "learning-lab.png"),
    ("eval-table.png", "eval-table.png"),
    ("tribunal-full.png", "tribunal-full.png"),
    ("delta-panel.png", "delta-panel.png"),
    ("atlas-failed-fixes.png", "atlas-failed-fixes.png"),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for src, dst in REUSE:
        data = (ARTICLE_IMAGES / src).read_bytes()
        (OUT / dst).write_bytes(data)
        print(f"copied {dst}")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for html, png in CODE_CARDS:
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto((ASSETS / html).as_uri())
            page.wait_for_timeout(300)
            # clip to the actual content height so the card has no dead space
            h = page.evaluate("document.body.scrollHeight")
            page.set_viewport_size({"width": 1280, "height": h})
            page.screenshot(path=str(OUT / png), full_page=True)
            page.close()
            print(f"rendered {png} ({h}px)")
        browser.close()
    print(f"done -> {OUT}")


if __name__ == "__main__":
    main()
