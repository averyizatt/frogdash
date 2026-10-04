"""Render the dash's bundled background and splash artwork to hardware/art/*.jpg.

Generated designs are original; photo designs use Creative Commons photos and the Ford oval
from tools/art-src (see tools/art-src/CREDITS.md). Each design is HTML/CSS/SVG
rendered at the dash's 1920 x 720 with Chromium, so it is easy to edit and re-run:

    python tools/make_art.py            # requires the browser-test Playwright install
"""
import asyncio
import base64
import math
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'hardware' / 'art'
BASE = '<style>html,body{margin:0;width:1920px;height:720px;overflow:hidden;background:#000;font-family:"DejaVu Sans","Segoe UI",Arial,sans-serif}</style>'

SRC = ROOT / 'tools' / 'art-src'
FONTS = '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Michroma&family=Oswald:wght@400;500;700&display=block">'


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


# ---- Original line art: Fox-body notchback side profile (front at left), 1000 x 300 units ----
FOX_BODY = ('M50 240 L42 214 L40 196 Q40 184 48 178 L62 163 C140 147 236 126 320 112 L410 39 C444 30 560 27 610 34 L690 99 '
            'C762 100 880 102 944 109 L951 122 L953 176 Q957 204 947 218 L941 240 L807.8 242 A70 70 0 1 0 676.2 242 L305.8 244 A70 70 0 1 0 174.2 242 Z')


def fox_wheel(cx, cy, ink, paper, solid):
    spokes = ''
    for i in range(5):
        a = math.radians(-90 + i * 72)
        points = [(10, a - .34), (40, a - .12), (40, a + .12), (10, a + .34)]
        spokes += '<path d="M' + ' L'.join(f'{cx + r * math.cos(t):.1f} {cy + r * math.sin(t):.1f}' for r, t in points) + f'Z" fill="{paper if solid else ink}"/>'
    if solid:
        return (f'<circle cx="{cx}" cy="{cy}" r="64" fill="{ink}"/><circle cx="{cx}" cy="{cy}" r="44" fill="{paper}"/>'
                f'<circle cx="{cx}" cy="{cy}" r="40" fill="{ink}"/>{spokes}<circle cx="{cx}" cy="{cy}" r="9" fill="{paper}"/><circle cx="{cx}" cy="{cy}" r="4" fill="{ink}"/>')
    return (f'<circle cx="{cx}" cy="{cy}" r="62" fill="{paper}" stroke="{ink}" stroke-width="5"/><circle cx="{cx}" cy="{cy}" r="43" fill="none" stroke="{ink}" stroke-width="3"/>'
            f'{spokes}<circle cx="{cx}" cy="{cy}" r="10" fill="{ink}"/><circle cx="{cx}" cy="{cy}" r="4" fill="{paper}"/>')


def fox(width, ink='#f2f2f2', paper='#0b0d10', glass='#262d34', solid=False, border=0, flip=False, style=''):
    """The car as an inline SVG. The body is squashed 10% towards the ground for a lowered
    stance; wheels stay round. border > 0 adds a sticker-style outer outline."""
    body = ''
    if border:
        body += f'<path d="{FOX_BODY}" fill="{ink}" stroke="{ink}" stroke-width="{border}" stroke-linejoin="round"/>'
    body += f'<path d="{FOX_BODY}" fill="{paper}" stroke="{ink}" stroke-width="5" stroke-linejoin="round"/>'
    body += f'<path d="M342 110 L416 47 L541 41 L548 107 Z" fill="{glass}"/><path d="M562 106 L556 41 L600 42 L648 103 Z" fill="{glass}"/>'
    body += f'<path d="M672 101 L622 44 L614 43 L662 102 Z" fill="{glass}"/>'
    line = f'stroke="{ink}" stroke-width="2.8" fill="none" stroke-linecap="round" stroke-linejoin="round"'
    body += f'<path d="M333 113 L328 240 M553 109 L557 241 M333 113 L553 109" {line}/>'
    body += f'<path d="M62 186 L178 181 M302 178 L680 176 M804 176 L951 178 M48 214 L170 210 M812 210 L951 208" {line}/>'
    body += f'<path d="M100 157 C180 142 250 130 316 120" {line}/>'
    body += f'<path d="M320 112 L332 99 L348 99 L340 111 Z" fill="{ink}"/><rect x="508" y="127" width="27" height="6" rx="3" fill="{ink}"/>'
    body += f'<path d="M58 166 L88 160 L88 177 L52 180 Z" fill="{ink}"/><path d="M926 113 L950 122 L952 164 L926 162 Z" fill="{ink}"/>'
    wheels = ''
    if border:
        wheels += ''.join(f'<circle cx="{cx}" cy="216" r="{64 + border / 2}" fill="{ink}"/>' for cx in (240, 742))
    wheels += fox_wheel(240, 216, ink, paper, solid) + fox_wheel(742, 216, ink, paper, solid)
    flipped = ' transform="translate(1000,0) scale(-1,1)"' if flip else ''
    return (f'<svg viewBox="-24 -4 1048 304" width="{width}" style="position:absolute;{style}"><g{flipped}>'
            f'<g transform="translate(0,28.2) scale(1,.9)">{body}</g>{wheels}</g></svg>')


def stage(inner, glow='#1a2129'):
    """Shared dark studio background for the splash screens."""
    return (f'<div style="position:absolute;inset:0;background:radial-gradient(ellipse 70% 85% at 50% 42%,{glow},#06080a 78%)"></div>'
            '<div style="position:absolute;inset:0;background:repeating-linear-gradient(0deg,#ffffff04 0 1px,transparent 1px 4px)"></div>' + inner)


def notice(text):
    return f'<div style="position:absolute;right:18px;bottom:12px;font:12px Oswald,sans-serif;letter-spacing:1px;color:#ffffff55">{text}</div>'


WIDE = "font-family:Michroma,'Eurostile Extended',sans-serif;text-transform:uppercase"

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
    # Splash screens: original line art, the Ford oval and the 1980s Mustang script (see CREDITS.md).
    ('splash-made-by-avery-izatt.jpg', 'splash', 'Made by Avery Izatt', stage(
        fox(1060, style='left:430px;top:22px') + f"""
<div style="position:absolute;left:0;right:0;top:364px;text-align:center;font:500 26px/1 Oswald,sans-serif;letter-spacing:18px;color:#d23a3a">MADE BY</div>
<div style="position:absolute;left:0;right:0;top:406px;text-align:center;{WIDE};font-size:118px;line-height:1;letter-spacing:6px;color:#f4f4f4">Avery Izatt</div>
<div style="position:absolute;left:660px;top:556px;width:600px;height:5px;background:linear-gradient(90deg,#d23a3a 0 33.3%,#f4f4f4 33.3% 66.6%,#2f6fd8 66.6%)"></div>
<div style="position:absolute;left:0;right:0;top:582px;text-align:center;font:400 22px/1 Oswald,sans-serif;letter-spacing:10px;color:#8d98a2">FOX BODY · 5.0</div>""")),
    ('splash-ford-oval.jpg', 'splash', 'Ford oval', f"""
<div style="position:absolute;inset:0;background:radial-gradient(ellipse 60% 75% at 50% 50%,#1b2a4a,#05070c 75%)"></div>
<div style="position:absolute;inset:0;background:repeating-linear-gradient(90deg,#ffffff05 0 1px,transparent 1px 4px)"></div>
<img src="{data('ford-oval.png')}" style="position:absolute;left:50%;top:44%;width:760px;transform:translate(-50%,-50%);filter:drop-shadow(0 18px 40px #000c)">
<div style="position:absolute;left:0;right:0;top:560px;text-align:center;font:500 30px/1 Oswald,sans-serif;letter-spacing:18px;color:#c9d3e4">FOX BODY MUSTANG</div>
{notice('Ford oval is a trademark of Ford Motor Company · not affiliated')}"""),
    ('splash-mustang-outline.jpg', 'splash', 'Mustang outline', stage(
        fox(1180, style='left:370px;top:14px') + f"""
<div style="position:absolute;left:0;right:0;top:344px;text-align:center;{WIDE};font-size:208px;line-height:1;letter-spacing:10px;color:#f4f4f4;-webkit-text-stroke:5px #f4f4f4">Mustang</div>
<div style="position:absolute;left:0;right:0;top:590px;text-align:center;font:400 22px/1 Oswald,sans-serif;letter-spacing:14px;color:#8d98a2">1979 – 1993</div>""")),
    ('splash-mustang-script.jpg', 'splash', 'Mustang script', stage(f"""
<img src="{data('mustang-script.png')}" style="position:absolute;left:50%;top:292px;width:1060px;transform:translate(-50%,-50%);filter:invert(1) drop-shadow(0 14px 30px #000a)">
<div style="position:absolute;left:560px;top:498px;width:800px;height:4px;background:#d23a3a"></div>
<div style="position:absolute;left:0;right:0;top:530px;text-align:center;font:500 30px/1 Oswald,sans-serif;letter-spacing:20px;color:#d9dee3">5.0 LITER · HIGH OUTPUT</div>
{notice('Mustang is a trademark of Ford Motor Company · not affiliated')}""", glow='#231416')),
    ('splash-fox-body.jpg', 'splash', 'Fox body sticker', f"""
<div style="position:absolute;inset:0;background:linear-gradient(160deg,#4a5057,#23272c 70%)"></div>
<div style="position:absolute;inset:0;background:repeating-linear-gradient(115deg,#ffffff06 0 2px,transparent 2px 7px)"></div>
{fox(1240, ink='#0c0d0f', paper='#f6f6f4', glass='#0c0d0f', solid=True, border=26, flip=True, style='left:340px;top:36px;filter:drop-shadow(0 22px 26px #0009)')}
<div style="position:absolute;left:0;right:0;top:468px;text-align:center;{WIDE};font-size:84px;line-height:1;letter-spacing:22px;color:#f6f6f4">Fox Body</div>
<div style="position:absolute;left:0;right:0;top:576px;text-align:center;font:400 24px/1 Oswald,sans-serif;letter-spacing:14px;color:#c3c9cf">NOTCHBACK · 1979 – 1993</div>"""),
    ('splash-five-point-oh.jpg', 'splash', '5.0', stage(
        fox(1000, style='left:820px;top:190px') + f"""
<div style="position:absolute;left:120px;top:150px;{WIDE};font-size:330px;line-height:1;letter-spacing:-6px;color:transparent;-webkit-text-stroke:5px #f4f4f4">5.0</div>
<div style="position:absolute;left:132px;top:520px;width:640px;height:5px;background:#d23a3a"></div>
<div style="position:absolute;left:132px;top:548px;font:500 34px/1 Oswald,sans-serif;letter-spacing:18px;color:#e04848">HIGH OUTPUT</div>""")),
    ('splash-built-not-bought.jpg', 'splash', 'Built not bought', stage(
        fox(900, style='left:960px;top:214px') + f"""
<div style="position:absolute;left:120px;top:176px;font:700 150px/.95 Oswald,sans-serif;color:#f5f5f5;text-transform:uppercase">Built<br><span style="color:#e2b13c">not bought</span></div>
<div style="position:absolute;left:124px;top:490px;width:520px;height:5px;background:#e2b13c"></div>
<div style="position:absolute;left:124px;top:518px;font:400 26px/1 Oswald,sans-serif;letter-spacing:12px;color:#8d98a2">GARAGE MADE</div>""", glow='#221d12')),
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
