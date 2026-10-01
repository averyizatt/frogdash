"""Render the dash's bundled background and splash artwork to hardware/art/*.jpg.

Generated designs are original; photo designs use Creative Commons photos and the Ford oval
from tools/art-src (see tools/art-src/CREDITS.md). Each design is HTML/CSS/SVG
rendered at the dash's 1920 x 720 with Chromium, so it is easy to edit and re-run:

    python tools/make_art.py            # requires the browser-test Playwright install
"""
import asyncio
import base64
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'hardware' / 'art'
BASE = '<style>html,body{margin:0;width:1920px;height:720px;overflow:hidden;background:#000;font-family:"DejaVu Sans","Segoe UI",Arial,sans-serif}</style>'

SRC = ROOT / 'tools' / 'art-src'
FONTS = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Oswald:wght@400;500;700&display=block">'


def data(name):
    """A source photo as a data URI (set_content pages cannot load local files)."""
    mime = 'image/png' if name.endswith('.png') else 'image/jpeg'
    return f'data:{mime};base64,' + base64.b64encode((SRC / name).read_bytes()).decode()


def photo(name, placement, filters):
    return f'<div style="position:absolute;inset:0;background:url({data(name)}) no-repeat {placement};filter:{filters}"></div>'


def photo_bg(name, focus):
    # Dim, soft and desaturated so gauges and warnings stay readable on top.
    return (f'<div style="position:absolute;inset:-20px;background:url({data(name)}) {focus} / cover;filter:blur(2px) brightness(.38) saturate(.75)"></div>'
            '<div style="position:absolute;inset:0;background:linear-gradient(90deg,#000a,#0003 30%,#0003 70%,#000a)"></div>')


def credit(text):
    return f'<div style="position:absolute;right:18px;bottom:12px;font:13px Oswald,sans-serif;letter-spacing:1px;color:#ffffff70">{text}</div>'


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
    # Photo backgrounds: real Fox-body Mustangs (credits in tools/art-src/CREDITS.md), darkened behind gauges.
    ('bg-photo-gt-red.jpg', 'background', 'Red GT (photo)', photo_bg('mustang-1986-gt-red.jpg', '58% 62%')),
    ('bg-photo-convertible.jpg', 'background', 'Black GT convertible (photo)', photo_bg('mustang-1988-gt-convertible.jpg', '62% 55%')),
    ('bg-photo-pace-car.jpg', 'background', 'Pace car (photo)', photo_bg('mustang-pace-car.jpg', '50% 70%')),
    ('bg-photo-fastback.jpg', 'background', 'Fastback (photo)', photo_bg('mustang-fox-fastback.jpg', '50% 50%')),
    ('bg-photo-gt-blue.jpg', 'background', 'Blue GT (photo)', photo_bg('mustang-1985-gt-blue.jpg', '60% 60%')),
    ('splash-made-by-avery-izatt.jpg', 'splash', 'Made by Avery Izatt', f"""
{photo('mustang-1986-gt-red.jpg', 'right 0 top 0 / 1240px auto', 'brightness(.9) saturate(1.1)')}
<div style="position:absolute;inset:0;background:linear-gradient(90deg,#050608 0 38%,#050608e6 50%,#05060800 78%)"></div>
<div style="position:absolute;left:120px;top:210px">
  <div style="font:500 30px/1 Oswald,sans-serif;letter-spacing:14px;color:#d23a3a">MADE BY</div>
  <div style="font:700 132px/1 Oswald,sans-serif;letter-spacing:4px;color:#f4f4f4;margin-top:14px;text-transform:uppercase">Avery Izatt</div>
  <div style="width:520px;height:6px;margin-top:26px;background:linear-gradient(90deg,#d23a3a 0 34%,#ffffff 34% 66%,#2f6fd8 66%)"></div>
  <div style="font:400 26px/1 Oswald,sans-serif;letter-spacing:9px;color:#9aa3ab;margin-top:24px">FOX BODY · 5.0</div>
</div>{credit('Photo: Sicnag, CC BY 2.0')}"""),
    ('splash-ford-oval.jpg', 'splash', 'Ford oval', f"""
<div style="position:absolute;inset:0;background:radial-gradient(ellipse 60% 75% at 50% 50%,#1b2a4a,#05070c 75%)"></div>
<div style="position:absolute;inset:0;background:repeating-linear-gradient(90deg,#ffffff05 0 1px,transparent 1px 4px)"></div>
<img src="{data('ford-oval.png')}" style="position:absolute;left:50%;top:44%;width:760px;transform:translate(-50%,-50%);filter:drop-shadow(0 18px 40px #000c)">
<div style="position:absolute;left:0;right:0;top:560px;text-align:center;font:500 30px/1 Oswald,sans-serif;letter-spacing:18px;color:#c9d3e4">FOX BODY MUSTANG</div>
{credit('Ford oval is a trademark of Ford Motor Company · not affiliated')}"""),
    ('splash-five-point-oh.jpg', 'splash', '5.0', f"""
{photo('mustang-1985-gt-blue.jpg', 'left -40px top -60px / 1300px auto', 'brightness(.75)')}
<div style="position:absolute;inset:0;background:linear-gradient(270deg,#040507 0 36%,#040507d9 50%,#04050700 76%)"></div>
<div style="position:absolute;right:130px;top:120px;text-align:right">
  <div style="font:400 380px/.9 'Bebas Neue',Oswald,sans-serif;color:#f2f2f2;letter-spacing:6px;text-shadow:0 10px 40px #000">5.0</div>
  <div style="font:500 34px/1 Oswald,sans-serif;letter-spacing:16px;color:#e04848;margin-top:6px">HIGH OUTPUT</div>
</div>{credit('Photo: Sicnag, CC BY 2.0')}"""),
    ('splash-fox-body.jpg', 'splash', 'Fox body pace car', f"""
{photo('mustang-pace-car.jpg', 'center 62% / cover', 'brightness(.62) saturate(.9)')}
<div style="position:absolute;inset:0;background:linear-gradient(180deg,#000000b0 0,#00000000 34%,#00000000 66%,#000000c0)"></div>
<div style="position:absolute;left:0;right:0;top:70px;text-align:center;font:700 120px/1 Oswald,sans-serif;letter-spacing:30px;color:#fff;text-shadow:0 6px 30px #000">FOX BODY</div>
<div style="position:absolute;left:0;right:0;bottom:84px;text-align:center;font:400 28px/1 Oswald,sans-serif;letter-spacing:14px;color:#d8d8d8">1979 – 1993</div>
{credit('Photo: priceman 141, CC BY 2.0')}"""),
    ('splash-built-not-bought.jpg', 'splash', 'Built not bought', f"""
{photo('mustang-1988-gt-convertible.jpg', 'right -80px top -40px / 1280px auto', 'brightness(.8) contrast(1.05)')}
<div style="position:absolute;inset:0;background:linear-gradient(90deg,#060606 0 36%,#060606e0 48%,#06060600 76%)"></div>
<div style="position:absolute;left:120px;top:190px;font:700 150px/.95 Oswald,sans-serif;color:#f5f5f5;text-transform:uppercase">Built<br><span style="color:#e2b13c">not bought</span></div>
{credit('Photo: Sicnag, CC BY 2.0')}"""),
]


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1920, 'height': 720})
        for name, _kind, _title, html in ART:
            await page.set_content(FONTS + BASE + html)
            await page.evaluate('document.fonts.ready')
            await page.wait_for_timeout(150)
            await page.screenshot(path=str(OUT / name), type='jpeg', quality=86)
        await browser.close()
    manifest = [{'name': name, 'kind': kind, 'title': title} for name, kind, title, _ in ART]
    (OUT / 'index.json').write_text(json.dumps(manifest, indent=1) + '\n', encoding='utf-8')
    print(f'Wrote {len(ART)} images to {OUT}')


if __name__ == '__main__':
    asyncio.run(main())
