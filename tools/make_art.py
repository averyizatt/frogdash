"""Render Frogdash's bundled background and splash artwork to hardware/art/*.jpg.

All artwork is original (no manufacturer logos or trademarks). Each design is HTML/CSS/SVG
rendered at the dash's 1920 x 720 with Chromium, so it is easy to edit and re-run:

    python tools/make_art.py            # requires the browser-test Playwright install
"""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'hardware' / 'art'
BASE = '<style>html,body{margin:0;width:1920px;height:720px;overflow:hidden;background:#000;font-family:"DejaVu Sans","Segoe UI",Arial,sans-serif}</style>'

# (file name, kind, title, HTML). Backgrounds stay dark and low-contrast behind gauges.
ART = [
    ('bg-foxbody-stripes.jpg', 'background', 'Fox-body stripes', '''
<div style="position:absolute;inset:0;background:linear-gradient(160deg,#1c1f22,#07090a 70%)"></div>
<div style="position:absolute;inset:0;background:repeating-linear-gradient(115deg,#ffffff03 0 2px,transparent 2px 6px)"></div>
<div style="position:absolute;left:1180px;top:-200px;width:1100px;height:1200px;transform:skewX(-28deg);
  background:linear-gradient(90deg,transparent 0 40px,#b3202a40 40px 120px,transparent 120px 150px,#c9c9c930 150px 190px,transparent 190px 220px,#1f4fa040 220px 300px,transparent 300px)"></div>'''),
    ('bg-night-highway.jpg', 'background', 'Night highway', '''
<div style="position:absolute;inset:0;background:linear-gradient(180deg,#0b1024 0%,#1a1236 40%,#2a1531 52%,#07070c 53%,#040406 100%)"></div>
<div style="position:absolute;left:0;right:0;top:300px;height:90px;background:radial-gradient(ellipse at 50% 100%,#ff6a3d40,transparent 70%)"></div>
<svg width="1920" height="720" style="position:absolute;inset:0"><g stroke-linecap="round">
<polyline points="0,720 930,382" stroke="#ffffff22" stroke-width="3" fill="none"/><polyline points="1920,720 990,382" stroke="#ffffff22" stroke-width="3" fill="none"/>
''' + ''.join(f'<line x1="{960 - 4 * i}" y1="{390 + i * i * .9}" x2="{960 - 4 * i - 2}" y2="{390 + i * i * .9 + 4 + i * .9}" stroke="#ffd26a55" stroke-width="{1 + i * .25}"/>' for i in range(2, 30, 3)) + '''
</g><g fill="#0d0d16">''' + ''.join(f'<rect x="{x}" y="{382 - h}" width="{w}" height="{h}"/>' for x, w, h in [(40, 70, 60), (120, 40, 110), (170, 90, 45), (300, 60, 80), (1400, 80, 70), (1500, 50, 130), (1560, 100, 50), (1700, 60, 90), (1780, 90, 40)]) + '</g></svg>'),
    ('bg-carbon-red.jpg', 'background', 'Carbon and red', '''
<div style="position:absolute;inset:0;background:repeating-linear-gradient(135deg,#ffffff0a 0 3px,transparent 3px 9px),repeating-linear-gradient(45deg,#ffffff07 0 3px,#0a0c0e 3px 9px)"></div>
<div style="position:absolute;inset:0;background:radial-gradient(ellipse 55% 70% at 100% 100%,#c0181a38,transparent 70%),linear-gradient(90deg,#000a,transparent 30%,transparent 70%,#000a)"></div>'''),
    ('bg-blueprint-coupe.jpg', 'background', 'Blueprint coupe', '''
<div style="position:absolute;inset:0;background:repeating-linear-gradient(0deg,#5fb6ff12 0 1px,transparent 1px 30px),repeating-linear-gradient(90deg,#5fb6ff12 0 1px,#06121e 1px 30px)"></div>
<svg width="1920" height="720" style="position:absolute;inset:0" fill="none" stroke="#7cc4ff3a" stroke-width="3" stroke-linejoin="round">
<path d="M600 520 L618 474 Q640 456 760 448 L880 404 Q946 378 1040 376 L1108 378 Q1150 382 1296 442 Q1362 452 1376 474 L1386 520 Z"/>
<path d="M900 406 L948 386 Q996 380 1036 381 L1040 440 L884 443 Z"/><path d="M1062 382 L1106 384 Q1146 388 1244 438 L1058 440 Z"/>
<path d="M620 488 H700 M1330 488 H1380" stroke-width="2"/>
<circle cx="742" cy="522" r="54"/><circle cx="742" cy="522" r="28"/><circle cx="1262" cy="522" r="54"/><circle cx="1262" cy="522" r="28"/>
<path d="M580 612 H1410 M600 602 V622 M1386 602 V622" stroke-width="2"/></svg>
<div style="position:absolute;left:960px;top:640px;transform:translateX(-50%);color:#7cc4ff55;font:600 20px monospace;letter-spacing:6px">SIDE ELEVATION · SCALE 1:12</div>'''),
    ('bg-tach-glow.jpg', 'background', 'Tach glow', '''
<div style="position:absolute;inset:0;background:radial-gradient(circle at 50% 120%,#1a0a0a,#050506 60%)"></div>
<svg width="1920" height="720" style="position:absolute;inset:0"><g transform="translate(960 900)">''' + ''.join(
        f'<line x1="0" y1="-700" x2="0" y2="{-640 if i % 5 else -600}" stroke="{"#ff3b30" if i > 44 else "#ffffff"}" stroke-opacity="{.35 if i > 44 else .12}" stroke-width="{6 if i % 5 == 0 else 3}" transform="rotate({-60 + i * 120 / 50})"/>' for i in range(51)) + '</g></svg>'),
    ('splash-made-by-avery-izatt.jpg', 'splash', 'Made by Avery Izatt', '''
<div style="position:absolute;inset:0;background:radial-gradient(ellipse at 50% 55%,#16222b,#040607 70%)"></div>
<div style="position:absolute;left:0;right:0;top:190px;text-align:center;color:#8a9aa6;font:700 28px/1 'DejaVu Sans',sans-serif;letter-spacing:16px">MADE BY</div>
<div style="position:absolute;left:0;right:0;top:250px;text-align:center;color:#f4f7f6;font:italic 700 132px/1 'DejaVu Serif',Georgia,serif;letter-spacing:2px">Avery Izatt</div>
<div style="position:absolute;left:50%;top:420px;transform:translateX(-50%);width:760px;height:3px;background:linear-gradient(90deg,transparent,#1cf29a,transparent)"></div>
<div style="position:absolute;left:0;right:0;top:450px;text-align:center;color:#1cf29a;font:700 30px/1 'DejaVu Sans Mono',monospace;letter-spacing:10px">FROGDASH DRIVER DISPLAY</div>'''),
    ('splash-five-point-oh.jpg', 'splash', '5.0 retro', '''
<div style="position:absolute;inset:0;background:linear-gradient(180deg,#0c0c10,#16161c 60%,#0a0a0d)"></div>
<div style="position:absolute;left:0;right:0;top:470px;height:120px;background:linear-gradient(180deg,#b3202a 0 34%,#0c0c10 34% 42%,#d7d7d7 42% 58%,#0c0c10 58% 66%,#1f4fa0 66%)"></div>
<div style="position:absolute;left:0;right:0;top:110px;text-align:center;font:italic 900 330px/1 'DejaVu Sans',Arial,sans-serif;letter-spacing:-10px;
  background:linear-gradient(180deg,#ffffff 0%,#c9d2da 45%,#5b6670 52%,#e6ebef 60%,#8e99a3 100%);-webkit-background-clip:text;color:transparent;filter:drop-shadow(0 6px 0 #000)">5.0</div>
<div style="position:absolute;right:170px;top:612px;color:#9aa4ad;font:700 26px/1 'DejaVu Sans',sans-serif;letter-spacing:12px">HIGH OUTPUT V8</div>'''),
    ('splash-fox-body.jpg', 'splash', 'Fox body', '''
<div style="position:absolute;inset:0;background:radial-gradient(ellipse at 50% 40%,#23262a,#060708 72%)"></div>
<div style="position:absolute;left:-40px;right:-40px;top:300px;height:14px;background:#b3202a;transform:skewY(-2deg)"></div>
<div style="position:absolute;left:-40px;right:-40px;top:326px;height:8px;background:#d7d7d7;transform:skewY(-2deg)"></div>
<div style="position:absolute;left:0;right:0;top:170px;text-align:center;color:#f4f7f6;font:italic 900 170px/1 'DejaVu Sans',Arial,sans-serif;letter-spacing:6px;text-shadow:0 8px 0 #000">FOX BODY</div>
<div style="position:absolute;left:0;right:0;top:420px;text-align:center;color:#9aa4ad;font:700 34px/1 'DejaVu Sans',sans-serif;letter-spacing:22px">1979 · 1993</div>'''),
    ('splash-built-not-bought.jpg', 'splash', 'Built not bought', '''
<div style="position:absolute;inset:0;background:repeating-linear-gradient(135deg,#ffffff06 0 3px,transparent 3px 9px),#0b0d0f"></div>
<div style="position:absolute;left:0;right:0;top:230px;text-align:center;color:#f4f7f6;font:900 150px/1 'DejaVu Sans Mono',monospace;letter-spacing:4px">BUILT</div>
<div style="position:absolute;left:0;right:0;top:390px;text-align:center;color:#ff7a00;font:900 70px/1 'DejaVu Sans Mono',monospace;letter-spacing:26px">NOT BOUGHT</div>'''),
    ('splash-frogdash.jpg', 'splash', 'Frogdash', '''
<div style="position:absolute;inset:0;background:radial-gradient(ellipse at 50% 50%,#0f2a22,#040807 70%)"></div>
<svg width="1920" height="720" style="position:absolute;inset:0"><g transform="translate(960 300)" fill="none" stroke="#1cf29a" stroke-width="10" stroke-linecap="round">
<path d="M-160 60 A160 160 0 1 1 160 60" stroke-opacity=".25"/><path d="M-160 60 A160 160 0 0 1 90 -130"/><line x1="0" y1="20" x2="95" y2="-95" stroke="#fff"/></g></svg>
<div style="position:absolute;left:0;right:0;top:420px;text-align:center;color:#f4f7f6;font:800 120px/1 'DejaVu Sans',Arial,sans-serif;letter-spacing:18px">FROGDASH</div>'''),
]


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        for name, _kind, _title, html in ART:
            await page.set_content(BASE + html)
            await page.wait_for_timeout(50)
            await page.screenshot(path=str(OUT / name), type='jpeg', quality=86)
        await browser.close()
    manifest = [{'name': name, 'kind': kind, 'title': title} for name, kind, title, _ in ART]
    (OUT / 'index.json').write_text(json.dumps(manifest, indent=1) + '\n', encoding='utf-8')
    print(f'Wrote {len(ART)} images to {OUT}')


if __name__ == '__main__':
    asyncio.run(main())
