#!/usr/bin/env python3
"""Generates the original animations in this folder for the GA402 AniMe Matrix.

Each scene is drawn on a canvas in millimetres as the lid is seen from outside, then every
LED takes the brightness under its physical position and is written to the pixel that
`asusctl anime pixel-gif` reads for it. So the GIFs play pixel-perfect and right way up,
and shapes keep their proportions even though LEDs are spaced 7.7mm apart in a row but
only 2.8mm between rows.

Run it again after changing a scene: ./make_animations.py [scene name ...]
"""
import math
import os
import random
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- Lid geometry (same as the app; see rog-anime in asusctl 6.3.8) --------------------
LED_ROWS = 61
DIAG_SIZE = (74, 39)
MM_X, MM_Y = 7.7, 2.83             # LED spacing within a row / between rows
W, H = 270, 176                    # canvas size in mm, one canvas pixel per mm

def led_row_start(r):
    return 0 if r <= 11 else (r + 1) // 2 - 5

def led_row_length(r):
    return 34 if r <= 11 else 39 - r // 2

LEDS = [(r, i, led_row_start(r) + i - 0.5 * (r % 2))
        for r in range(LED_ROWS) for i in range(led_row_length(r))]

def diagonal_pixel(r, i):
    x0, y0 = ((r + 1) // 2, 5 - r // 2) if r <= 11 else (r - 5, 0)
    return x0 + i, DIAG_SIZE[1] - 1 - y0 - i

# asusctl's row 0 is at the bottom when seen from outside
CENTERS = [((x + 1) * MM_X, (LED_ROWS - r) * MM_Y) for r, _, x in LEDS]
PIXELS = [diagonal_pixel(r, i) for r, i, _ in LEDS]

# Averages roughly one LED's footprint (5mm wide, 3mm tall; applied twice) before sampling
FOOTPRINT = ImageFilter.Kernel((5, 5), [0] * 5 + [1] * 15 + [0] * 5, scale=15)

def visible_left(y):
    """Leftmost canvas x that has LEDs at height y (the lid's top-left corner is cut off)."""
    return 15 + max(0.0, 138 - y) * 1.36

def to_native(canvas):
    soft = canvas.filter(FOOTPRINT).filter(FOOTPRINT)
    src = soft.load()
    out = Image.new("L", DIAG_SIZE, 0)
    dst = out.load()
    for (cx, cy), (px, py) in zip(CENTERS, PIXELS):
        dst[px, py] = src[min(int(cx), W - 1), min(int(cy), H - 1)]
    return out

def save(name, canvases, ms):
    frames = [to_native(c) for c in canvases]
    path = os.path.join(OUT_DIR, name + ".gif")
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=ms, loop=0,
                   disposal=1, optimize=False)
    print(f"{path}: {len(frames)} frames, {len(frames) * ms / 1000:.1f}s")

# ---- Drawing helpers --------------------------------------------------------------------
TAU = 2 * math.pi

def new_canvas(background=0):
    img = Image.new("L", (W, H), int(background))
    return img, ImageDraw.Draw(img)

def box(x, y, r, ry=None):
    return (x - r, y - (r if ry is None else ry), x + r, y + (r if ry is None else ry))

def ease(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)

def lerp(a, b, t):
    return a + (b - a) * t

def cycle(t, n, k=1, phase=0.0):
    """sin() that repeats exactly k times over n frames, so loops are seamless."""
    return math.sin(TAU * k * t / n + phase)

def draw_particles(d, particles):
    """Particles are (x, y, radius, level); drawing dim ones first makes overlaps look additive."""
    for x, y, r, level in sorted(particles, key=lambda p: p[3]):
        if level > 0:
            d.ellipse(box(x, y, r), fill=int(min(255, level)))

def bolt_points(rng, a, b, roughness, depth=5):
    """Jagged lightning path from a to b by repeated midpoint displacement."""
    pts = [a, b]
    for level in range(depth):
        out = [pts[0]]
        for p, q in zip(pts, pts[1:]):
            dx, dy = q[0] - p[0], q[1] - p[1]
            length = math.hypot(dx, dy) or 1
            off = rng.uniform(-1, 1) * roughness / (1.6 ** level)
            out += [((p[0] + q[0]) / 2 - dy / length * off, (p[1] + q[1]) / 2 + dx / length * off), q]
        pts = out
    return pts

def draw_bolt(d, pts, level=255):
    d.line(pts, fill=level // 3, width=9)
    d.line(pts, fill=level, width=3)

def loop_crossfade(frames, overlap):
    """Blends the extra frames at the end into the start so stochastic scenes loop smoothly."""
    n = len(frames) - overlap
    out = frames[:n]
    for k in range(overlap):
        out[k] = Image.blend(frames[n + k], frames[k], (k + 1) / (overlap + 1))
    return out

def twinkling_stars(rng, count, n, max_y=H, min_level=25, max_level=90):
    spots = [c for c in CENTERS if c[1] < max_y]
    return [(x, y, rng.uniform(0, TAU), rng.choice((2, 3)), min_level, max_level)
            for x, y in rng.sample(spots, count)]

def draw_stars(d, stars, t, n):
    for x, y, phase, k, lo, hi in stars:
        level = lerp(lo, hi, 0.5 + 0.5 * cycle(t, n, k, phase))
        d.ellipse(box(x, y, 2.5, 1.5), fill=int(level))

# ---- Wizard vs Dragon --------------------------------------------------------------------
# This scene is drawn upside down: it is laid out for the lid turned 180 degrees (cut corner at
# the bottom right) and rotated back before sampling.
WIZ_X, GROUND = 36, 171

def draw_wizard(d, t, n, raise_amount, orb_radius, orb_level):
    """Returns the staff orb's position."""
    x, g = WIZ_X, GROUND
    sway = 2 * cycle(t, n, 4)
    d.polygon([(x - 15, g), (x + 13, g), (x + 5, g - 33), (x - 7, g - 33)], fill=55, outline=200, width=2)
    d.ellipse(box(x - 1, g - 39, 6), fill=170)                                             # head
    d.polygon([(x - 5, g - 37), (x + 5, g - 37), (x + 1 + sway / 2, g - 23)], fill=235)    # beard
    d.polygon([(x - 14, g - 44), (x + 13, g - 44), (x + 12, g - 48), (x - 13, g - 48)], fill=210)
    d.polygon([(x - 8, g - 46), (x + 8, g - 46), (x - 11 + sway, g - 74)], fill=55, outline=210, width=2)
    d.ellipse(box(x - 11 + sway, g - 74, 2), fill=255)                                     # hat star
    lift = raise_amount
    top = (x + 21 + 4 * lift, g - 64 - 16 * lift)
    hand = (x + 19 + 2 * lift, g - 34 - 12 * lift)
    d.line([(x + 17, g - 16 * lift), top], fill=110, width=4)                             # staff
    d.line([(x + 3, g - 31), hand], fill=140, width=5)                                    # arm
    if orb_level > 0:
        d.ellipse(box(*top, orb_radius * 2.2), fill=int(orb_level * 0.3))
        d.ellipse(box(*top, orb_radius), fill=int(orb_level))
    return top

def bezier(p0, p1, p2, steps):
    return [((1 - u) ** 2 * p0[0] + 2 * (1 - u) * u * p1[0] + u * u * p2[0],
             (1 - u) ** 2 * p0[1] + 2 * (1 - u) * u * p1[1] + u * u * p2[1])
            for u in (k / steps for k in range(steps + 1))]

def draw_wing(d, sx, sy, flap, level, scale=1.0):
    """Bony bat wing reaching back (right); flap 1 is fully up, -1 fully down."""
    up = (flap if flap > 0 else flap * 0.7) * scale

    def at(dx, dy):
        return sx + dx * scale, sy - dy * up - 2

    elbow, wrist = at(14, 18), at(24, 42)
    tips = [at(14, 62), at(40, 58), at(60, 38), at(44, 4)]
    membrane = [(sx, sy), elbow, wrist, tips[0]]
    for a, b in zip(tips, tips[1:]):
        # trailing edge sags towards the wrist between fingers
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        membrane += [(lerp(mid[0], wrist[0], 0.3), lerp(mid[1], wrist[1], 0.3)), b]
    d.polygon(membrane + [(sx + 8, sy + 2)], fill=int(level * 0.22))
    d.line([(sx, sy), elbow, wrist], fill=int(level), width=3)
    for tip in tips:
        d.line([wrist, tip], fill=int(level * 0.75), width=2)
    claw = at(16, 50)
    d.line([wrist, claw, (claw[0] - 3, claw[1] + 2)], fill=int(level), width=2)

def draw_dragon(d, x, y, flap, jaw, tail_phase, rear=0.0):
    """Dragon facing left with its body centred on (x, y); rear > 0 pulls the head back and up,
    rear < 0 lunges it forward. Returns the mouth position."""
    hx, hy = x - 52 + 10 * rear, y - 20 - 8 * rear

    # Long tail streaming back, with a wave running along it, ending in a barb
    tail = [(x + 18, y + 3)]
    for k in range(8):
        ang = -0.15 - k * 0.06 + 0.3 * math.sin(tail_phase - k * 0.7)
        tail.append((tail[-1][0] + 8 * math.cos(ang), tail[-1][1] + 8 * math.sin(ang)))
    for k in range(8):
        d.line([tail[k], tail[k + 1]], fill=170, width=max(1, 5 - k // 2))
    (px, py), (tx, ty) = tail[-2], tail[-1]
    ang = math.atan2(ty - py, tx - px)
    ux, uy = math.cos(ang), math.sin(ang)
    d.polygon([(tx + ux * 8, ty + uy * 8), (tx - uy * 4 - ux * 2, ty + ux * 4 - uy * 2), (tx, ty),
               (tx + uy * 4 - ux * 2, ty - ux * 4 - uy * 2)], fill=230)

    draw_wing(d, x + 6, y - 8, math.sin(math.asin(max(-1, min(1, flap))) + 0.5), 85, 0.85)   # far wing

    # Legs tucked under, claws forward
    d.line([(x + 12, y + 5), (x + 5, y + 14), (x + 12, y + 20), (x + 6, y + 22)], fill=170, width=3)
    d.line([(x - 14, y + 7), (x - 19, y + 14), (x - 13, y + 18), (x - 18, y + 20)], fill=170, width=3)

    torso = [(x - 22, y - 6), (x - 16, y + 9), (x + 4, y + 10), (x + 22, y + 5), (x + 20, y - 5), (x - 4, y - 10)]
    d.polygon(torso, fill=50, outline=210, width=2)

    # S-shaped neck, thick at the chest and thin at the head
    neck = bezier((x - 18, y - 5), (x - 30, y - 28 - 10 * rear), (hx + 7, hy + 1), 6)
    for k, (a, b) in enumerate(zip(neck, neck[1:])):
        d.line([a, b], fill=210, width=10 - k)
    for k, (a, b) in enumerate(zip(neck, neck[1:])):
        d.line([a, b], fill=50, width=max(1, 5 - k))
    for (ax, ay), (bx, by) in zip(neck[1:], neck[2:]):                                   # neck spines
        d.polygon([(ax, ay - 4), (bx, by - 4), ((ax + bx) / 2 + 3, (ay + by) / 2 - 10)], fill=200)
    for k in range(4):                                                                    # back spines
        sx = x - 14 + k * 9
        d.polygon([(sx - 3, y - 9), (sx + 4, y - 8), (sx + 4, y - 16)], fill=200)

    # Wedge-shaped head: long snout, heavy brow, horns swept back
    drop = 12 * jaw
    d.polygon([(hx + 6, hy + 4), (hx - 18, hy + 5 + drop), (hx - 15, hy + 8 + drop), (hx + 4, hy + 9)],
              fill=160)                                                                    # lower jaw
    d.polygon([(hx + 9, hy - 3), (hx - 2, hy - 7), (hx - 10, hy - 4), (hx - 23, hy + 1),
               (hx - 21, hy + 4), (hx + 7, hy + 5)], fill=200)                             # skull & snout
    d.line([(hx + 7, hy - 4), (hx + 17, hy - 10), (hx + 27, hy - 9)], fill=230, width=3)  # horns
    d.line([(hx + 3, hy - 6), (hx + 10, hy - 15), (hx + 19, hy - 18)], fill=200, width=2)
    d.ellipse(box(hx - 4, hy - 3, 2.5, 1.2), fill=0)                                     # slit eye
    d.ellipse(box(hx - 4, hy - 3, 1.6, 1), fill=255)

    draw_wing(d, x - 6, y - 8, flap, 235)                                                # near wing
    return hx - 20, hy + 5 + drop * 0.6

def wizard_vs_dragon():
    n = 170
    rng = random.Random(7)
    stars = [(W - x, H - y, *rest) for x, y, *rest in twinkling_stars(rng, 22, n)]
    stars = [st for st in stars if st[1] < 150]
    shield_center, shield_radius = (WIZ_X + 4, GROUND - 36), 36
    fire, sparks, smoke = [], [], []
    flap_phase = flash = 0.0
    frames = []
    for t in range(n):
        # Dragon flies in, hovers, gets struck, and flees; it is off screen at the loop point
        if t < 28:
            k = ease(t / 28)
            dx, dy = lerp(330, 160, k), lerp(10, 64, k)
        elif t < 106:
            dx, dy = 160, 64 + 3 * math.sin(t * 0.3)
        elif t < 118:
            dx, dy = 160 + 14 * ease((t - 106) / 6), 64 - 4 * ease((t - 106) / 6)
        else:
            k = (t - 118) / 22
            dx, dy = 174 + 160 * k * k, 60 - 100 * k * k
        # Powerful downstroke, slower recovery
        speed = TAU / (7 if t >= 112 else 12)
        flap_phase += speed * (1.5 if math.cos(flap_phase) < 0 else 0.75)
        flap = math.sin(flap_phase)
        rear = (ease((t - 28) / 8) * (1 - ease((t - 42) / 3))
                - 0.6 * ease((t - 42) / 3) * (1 - ease((t - 80) / 8)))
        jaw = ease((t - 34) / 8) * (1 - ease((t - 80) / 4))
        shield = ease((t - 38) / 6) * (1 - ease((t - 84) / 5))
        raise_amount = ease((t - 84) / 6) * (1 - ease((t - 150) / 8))
        charging = 86 <= t < 104
        orb_radius = 3.5 + (4 * ease((t - 86) / 18) if t < 108 else 4 * (1 - ease((t - 108) / 6)))
        orb_level = 150 + 60 * cycle(t, n, 10) if not charging else 255

        if t == 104:
            flash = 60
        background = flash
        flash *= 0.55
        img, d = new_canvas(background)
        draw_stars(d, stars, t, n)
        d.polygon([(0, H), (0, 168), (60, 166), (120, 169), (200, 165), (W, 168), (W, H)], fill=45)

        # Fire breath, deflected by the shield
        if 44 <= t < 80:
            mx, my = mouth
            for _ in range(3):
                ang = math.atan2(shield_center[1] - my, shield_center[0] - mx) + rng.uniform(-0.18, 0.18)
                speed = rng.uniform(5, 7)
                fire.append([mx, my, math.cos(ang) * speed, math.sin(ang) * speed, 0, rng.randint(16, 22)])
        for p in fire:
            p[0] += p[2]
            p[1] += p[3]
            p[4] += 1
            rx, ry = p[0] - shield_center[0], p[1] - shield_center[1]
            dist = math.hypot(rx, ry)
            if shield > 0.5 and dist < shield_radius and p[2] * rx + p[3] * ry < 0:
                nx, ny = rx / dist, ry / dist
                dot = p[2] * nx + p[3] * ny
                p[2], p[3] = (p[2] - 2 * dot * nx) * 0.35, (p[3] - 2 * dot * ny) * 0.35 - 0.6
                p[5] = min(p[5], p[4] + 6)
        fire = [p for p in fire if p[4] < p[5]]
        draw_particles(d, [(p[0], p[1], 1.8 + p[4] * 0.18, rng.uniform(0.6, 1) * 255 * (1 - p[4] / p[5]) ** 0.6)
                           for p in fire])

        if shield > 0:
            hit = any(math.hypot(p[0] - shield_center[0], p[1] - shield_center[1]) < shield_radius + 6
                      for p in fire)
            level = shield * (230 if hit else 140 + 50 * cycle(t, n, 20))
            d.arc(box(*shield_center, shield_radius), -120, 30, fill=int(level), width=3)

        # Charging sparkles drawn in to the orb
        orb = draw_wizard(d, t, n, raise_amount, orb_radius, orb_level)
        if charging:
            for _ in range(3):
                ang = rng.uniform(0, TAU)
                sparks.append([ang, rng.uniform(30, 45), 0])
        for s in sparks:
            s[1] *= 0.78
            s[2] += 1
        sparks = [s for s in sparks if s[1] > 4]
        draw_particles(d, [(orb[0] + math.cos(a) * r, orb[1] + math.sin(a) * r, 1.8, 120 + 100 * age / 8)
                           for a, r, age in sparks])

        # Lightning strike
        if 104 <= t < 112:
            strike_rng = random.Random(t // 2)
            pts = bolt_points(strike_rng, orb, (dx - 4, dy), 28)
            draw_bolt(d, pts)
            for _ in range(2):
                start = pts[strike_rng.randrange(8, len(pts) - 8)]
                end = (start[0] + strike_rng.uniform(5, 25), start[1] + strike_rng.uniform(-25, 25))
                d.line(bolt_points(strike_rng, start, end, 8, 3), fill=170, width=2)

        # Dragon, flickering while it is hit, trailing smoke as it flees
        if 112 <= t < 140 and t % 2 == 0:
            smoke.append([dx + 25, dy + 4, 0])
        for s in smoke:
            s[1] -= 0.4
            s[2] += 1
        smoke = [s for s in smoke if s[2] < 16]
        draw_particles(d, [(x, y, 3 + age * 0.5, 80 * (1 - age / 16)) for x, y, age in smoke])
        if not (106 <= t < 118 and t % 2):
            mouth = draw_dragon(d, dx, dy, flap, jaw, t * 0.35, rear)
            if 34 <= t < 80:
                glow = ease((t - 34) / 10)
                d.ellipse(box(*mouth, 3 + 3 * glow), fill=int(120 + 135 * glow))

        frames.append(img)
    return [f.transpose(Image.Transpose.ROTATE_180) for f in wizard_vs_dragon_finale(frames, n)]

def wizard_vs_dragon_finale(frames, n):
    """A victory firework over the empty sky after the dragon has fled."""
    rng = random.Random(11)
    start, burst_at = (WIZ_X + 25, GROUND - 82), (150, 42)
    sparks = []
    for t in range(140, 168):
        d = ImageDraw.Draw(frames[t])
        if t < 150:
            k = ease((t - 140) / 10)
            x, y = lerp(start[0], burst_at[0], k), lerp(start[1], burst_at[1], k)
            draw_particles(d, [(lerp(start[0], burst_at[0], k - j * 0.05),
                                lerp(start[1], burst_at[1], k - j * 0.05), 2, 200 - j * 50) for j in range(4)])
        elif t == 150:
            for k in range(30):
                ang = TAU * k / 30 + rng.uniform(-0.05, 0.05)
                speed = rng.uniform(3.5, 5.5)
                sparks.append([*burst_at, math.cos(ang) * speed, math.sin(ang) * speed * 0.8])
        for s in sparks:
            s[0] += s[2]
            s[1] += s[3]
            s[2] *= 0.9
            s[3] = s[3] * 0.9 + 0.25
        if t >= 150:
            age = (t - 150) / 18
            draw_particles(d, [(x, y, 2.2, 255 * (1 - age) ** 1.3) for x, y, _, _ in sparks])
            if t < 153:
                d.ellipse(box(*burst_at, 10 - 2 * (t - 150)), fill=255)
    return frames

# ---- Other scenes ------------------------------------------------------------------------
def hyperspace():
    n = 60
    rng = random.Random(3)
    cx, cy = 172, 98
    stars = [(rng.uniform(0, TAU), rng.random(), rng.choice((1, 1, 2))) for _ in range(150)]
    frames = []
    for t in range(n):
        img, d = new_canvas()
        d.ellipse(box(cx, cy, 10 + 3 * cycle(t, n, 4)), fill=45)
        lines = []
        for ang, phase, k in stars:
            p = (phase + k * t / n) % 1
            head = 6 + 230 * p ** 2.2
            tail = 6 + 230 * max(0.0, p - 0.07 * k) ** 2.2
            level = 255 * min(1.0, p * 1.8)
            lines.append((level, ang, head, tail, 3 if p > 0.55 else 2))
        for level, ang, head, tail, width in sorted(lines):
            c, s = math.cos(ang), math.sin(ang)
            d.line([(cx + c * tail, cy + s * tail * 0.75), (cx + c * head, cy + s * head * 0.75)],
                   fill=int(level), width=width)
        frames.append(img)
    return frames

def digital_rain():
    n = 90
    rng = random.Random(5)
    streams = []
    for _ in range(30):
        x = rng.uniform(4, W - 4)
        streams.append((x, rng.random(), rng.choice((1, 1, 2)), rng.uniform(40, 90)))
    cell = 6
    frames = []
    for t in range(n):
        img, d = new_canvas()
        for x, phase, laps, length in streams:
            head = ((phase + laps * t / n) % 1) * (H + length) - 4
            for j in range(int(length // cell)):
                y = head - j * cell
                if not 0 <= y < H + cell:
                    continue
                glyph = random.Random(hash((round(x), int(y // cell), t // 3))).random()
                fade = (1 - j * cell / length) ** 1.5
                level = 255 if j == 0 else 200 * fade * (0.45 + 0.55 * glyph)
                d.rectangle((x - 2, y - cell + 1.5, x + 2, y), fill=int(level))
        frames.append(img)
    return frames

def inferno():
    """The classic demoscene fire: each cell copies the one below, shifted and cooled at random."""
    n, overlap, top = 100, 16, 34
    rng = random.Random(9)
    cols, rows = 70, 62
    heat = [[0] * cols for _ in range(rows)]
    frames = []
    for t in range(80 + n + overlap):
        a = TAU * t / 40
        heat[0] = [top if math.sin(x * 0.45 + a) + math.sin(x * 0.17 - a * 0.5) > 0 else top - 12
                   for x in range(cols)]
        for y in range(1, rows):
            below, row = heat[y - 1], heat[y]
            for x in range(cols):
                row[(x + rng.randrange(3) - 1) % cols] = max(0, below[x] - rng.choice((0, 1, 1, 1, 2)))
        if t < 80:
            continue
        data = bytes(int(255 * (h / top) ** 1.7) for y in reversed(range(rows)) for h in heat[y])
        small = Image.frombytes("L", (cols, rows), data)
        frames.append(small.resize((W, H), Image.Resampling.BILINEAR))
    return loop_crossfade(frames, overlap)

def thunderstorm():
    n = 120
    rng = random.Random(13)
    drops = [(rng.uniform(0, W + 60), rng.random(), rng.choice((2, 3)), rng.randint(110, 190))
             for _ in range(70)]
    clouds = [(rng.uniform(0, W), rng.uniform(4, 18), rng.uniform(25, 45)) for _ in range(7)]
    strikes = {24: 0, 27: 0, 78: 1, 80: 1, 83: 1}
    flash = 0.0
    frames = []
    for t in range(n):
        if t in strikes:
            flash = 55
        img, d = new_canvas(flash)
        flash *= 0.5
        for x, y, r in clouds:
            cx = (x + W * t / n) % (W + 2 * r) - r
            d.ellipse(box(cx, y, r, r * 0.45), fill=30)
        for x, phase, laps, level in drops:
            y = ((phase + laps * t / n) % 1) * (H + 20) - 10
            px = (x - y * 0.35) % (W + 60) - 30
            d.line([(px, y), (px + 3.5, y - 10)], fill=level, width=2)
            if y > H - 6:
                d.ellipse(box(px, H - 2, 4, 1.5), fill=level // 2)
        if t in strikes:
            bolt_rng = random.Random(strikes[t] * 100 + t)
            top = (bolt_rng.uniform(215, 255), 0) if strikes[t] == 0 else (245, 0)
            end = (150, H) if strikes[t] == 0 else (185, H)
            pts = bolt_points(bolt_rng, top, end, 40, 6)
            draw_bolt(d, pts)
            for _ in range(3):
                start = pts[bolt_rng.randrange(10, len(pts) - 20)]
                branch_end = (start[0] + bolt_rng.uniform(-50, 40), start[1] + bolt_rng.uniform(20, 50))
                d.line(bolt_points(bolt_rng, start, branch_end, 14, 4), fill=150, width=2)
        frames.append(img)
    return frames

def draw_saucer(d, x, y, light):
    d.ellipse(box(x, y - 4, 6, 5), fill=110)
    d.ellipse(box(x, y, 13, 4), fill=190)
    d.ellipse(box(x, y, 2.5, 1.5), fill=int(light))

def space_battle():
    n = 180
    rng = random.Random(21)
    ship_y = 164
    slots = [(150, 42), (190, 30), (228, 30), (176, 78), (218, 64), (252, 52), (130, 104)]
    order = [6, 3, 0, 4, 1, 5, 2]
    shots = {k: 14 + 20 * j for j, k in enumerate(order)}
    stars = [(rng.uniform(0, W), rng.uniform(0, H), rng.choice((1, 2))) for _ in range(30)]
    explosions = []
    frames = []
    for t in range(n):
        img, d = new_canvas()
        for x, y, k in stars:
            sy = (y + H * k * t / n) % H
            d.ellipse(box(x, sy, 2, 1.2), fill=40 * k)

        def enemy_pos(k, t=t):
            x, y = slots[k]
            return x + 6 * cycle(t, n, 2, k), y + 3 * cycle(t, n, 6, k * 0.8)

        # Ship glides under its next target, then back to the centre for the new wave
        targets = [(shots[k] - 14, shots[k] - 3, enemy_pos(k, shots[k])[0]) for k in order]
        ship_x = 135.0
        prev = 135.0
        for start, end, tx in targets:
            if t >= start:
                ship_x = lerp(prev, tx, ease((t - start) / (end - start)))
            prev = tx
        if t >= 158:
            ship_x = lerp(prev, 135.0, ease((t - 158) / 16))

        for k, (sx, sy) in enumerate(slots):
            shot = shots[k]
            bullet_y = ship_y - 14 - 9 * (t - shot)
            ex, ey = enemy_pos(k)
            hit_t = shot + int((ship_y - 14 - ey) / 9) + 1
            if shot <= t < hit_t:
                bx = enemy_pos(k, shot)[0]
                d.line([(bx, bullet_y), (bx, bullet_y + 8)], fill=255, width=3)
            if t == hit_t:
                for _ in range(16):
                    ang, speed = rng.uniform(0, TAU), rng.uniform(1.5, 4)
                    explosions.append([ex, ey, math.cos(ang) * speed, math.sin(ang) * speed, 0])
            alive = t < hit_t or t >= 160
            if alive:
                drop = (1 - ease((t - 160) / 16)) * 90 if t >= 160 else 0
                draw_saucer(d, ex, ey - drop, 255 if (t // 4 + k) % 3 else 120)
            if t == hit_t:
                d.ellipse(box(ex, ey, 10), fill=230)

        for p in explosions:
            p[0] += p[2]
            p[1] += p[3]
            p[2] *= 0.92
            p[3] *= 0.92
            p[4] += 1
        explosions = [p for p in explosions if p[4] < 14]
        draw_particles(d, [(x, y, 2.2, 255 * (1 - age / 14)) for x, y, _, _, age in explosions])

        d.polygon([(ship_x, ship_y - 14), (ship_x - 11, ship_y + 4), (ship_x, ship_y),
                   (ship_x + 11, ship_y + 4)], fill=210)
        d.ellipse(box(ship_x, ship_y + 6, 3, 2 + 1.5 * (t % 2)), fill=150 + 100 * (t % 2))
        frames.append(img)
    return frames

def heartbeat():
    n = 80
    baseline = 150
    beats = (95, 230)

    def trace(x):
        y = baseline
        for c in beats:
            u = x - c
            y -= 6 * math.exp(-((u + 24) / 6) ** 2)          # P wave
            y += 7 * math.exp(-((u + 5) / 2) ** 2)           # Q
            y -= 58 * math.exp(-(u / 2.4) ** 2)              # R spike
            y += 16 * math.exp(-((u - 5) / 2.2) ** 2)        # S
            y -= 11 * math.exp(-((u - 26) / 7) ** 2)         # T wave
        return y

    points = [(x, trace(x)) for x in range(W)]
    frames = []
    for t in range(n):
        img, d = new_canvas()
        head = W * t / n
        for x in range(W - 1):
            age = ((head - x) % W) / W
            level = 255 * (1 - age) ** 2.5
            if level > 8:
                d.line([points[x], points[x + 1]], fill=int(level), width=3)
        hy = trace(head)
        d.ellipse(box(head, hy, 4), fill=255)
        since = min(((head - c) % W) / (W / n) for c in beats)
        scale = 1 + 0.35 * math.exp(-since / 4)
        draw_heart(d, 228, 34, 13 * scale, int(150 + 105 * math.exp(-since / 5)))
        frames.append(img)
    return frames

def draw_heart(d, x, y, size, level):
    r = size * 0.55
    d.ellipse(box(x - r * 0.9, y - r * 0.5, r), fill=level)
    d.ellipse(box(x + r * 0.9, y - r * 0.5, r), fill=level)
    d.polygon([(x - r * 1.85, y - r * 0.2), (x + r * 1.85, y - r * 0.2), (x, y + size * 1.25)], fill=level)

def plasma():
    n = 90
    gw, gh = 90, 59
    frames = []
    for t in range(n):
        a = TAU * t / n
        cx, cy = 45 + 25 * math.cos(a), 30 + 18 * math.sin(2 * a)
        data = bytearray(gw * gh)
        for y in range(gh):
            for x in range(gw):
                v = (math.sin(x * 0.11 + a) + math.sin((x * 0.6 + y) * 0.12 - 2 * a)
                     + math.sin(math.hypot(x - cx, (y - cy) * 1.4) * 0.22 - a))
                data[y * gw + x] = int(255 * (0.5 + 0.5 * math.sin(v * math.pi)) ** 2)
        frames.append(Image.frombytes("L", (gw, gh), bytes(data)).resize((W, H), Image.Resampling.BILINEAR))
    return frames

def ripples():
    n, life = 120, 40
    rng = random.Random(17)
    spots = [c for c in CENTERS if c[0] > visible_left(c[1]) + 25 and 15 < c[1] < H - 12]
    drops = [(int(k * n / 10 + rng.uniform(0, 6)), *rng.choice(spots)) for k in range(10)]
    frames = []
    for t in range(n):
        img, d = new_canvas()
        rings = []
        for t0, x, y in drops:
            age = (t - t0) % n
            if age >= life:
                continue
            fade = (1 - age / life) ** 1.4
            for lag, gain in ((0, 1.0), (9, 0.6), (18, 0.35)):
                r = 2 + (age - lag) * 2.4
                if r > 3:
                    rings.append((255 * fade * gain, x, y, r))
            if age < 3:
                d.ellipse(box(x, y, 5 - age), fill=255)
        for level, x, y, r in sorted(rings):
            d.ellipse(box(x, y, r), outline=int(level), width=3)
        frames.append(img)
    return frames

def equalizer():
    n = 96
    bars, bar_w, pitch = 11, 14, 24.5
    rng = random.Random(23)
    voices = [[(rng.choice((1, 2, 3, 4, 6)), rng.uniform(0, TAU), rng.uniform(0.3, 1)) for _ in range(3)]
              for _ in range(bars)]

    def height(b, t):
        v = sum(amp * cycle(t, n, k, ph) for k, ph, amp in voices[b]) / 3
        beat = math.exp(-((t % 12) / 3)) * (1 - b / bars)
        return 12 + 150 * min(1.0, max(0.0, 0.35 + 0.6 * v + 0.35 * beat)) * (0.55 + 0.45 * b / bars)

    heights = [[height(b, t) for t in range(n)] for b in range(bars)]
    frames = []
    for t in range(n):
        img, d = new_canvas()
        for b in range(bars):
            x = 3 + b * pitch
            h = heights[b][t]
            peak = max(heights[b][(t - s) % n] - 0.35 * s * s for s in range(30))
            d.rectangle((x, H - h, x + bar_w, H), fill=200)
            d.rectangle((x, H - peak - 4, x + bar_w, H - peak - 1), fill=255)
        for r in range(0, LED_ROWS, 3):       # dark gaps split bars into segments
            y = (LED_ROWS - r) * MM_Y
            d.line([(0, y), (W, y)], fill=0, width=2)
        frames.append(img)
    return frames

# ---- Dark Souls ---------------------------------------------------------------------------
def fire_layers(n, overlap, cols, rows, seed, top=24):
    """Frames of a small looping campfire (same algorithm as Inferno), hottest in the middle."""
    rng = random.Random(seed)
    heat = [[0] * cols for _ in range(rows)]
    mid = (cols - 1) / 2
    frames = []
    for t in range(60 + n + overlap):
        heat[0] = [int(top * max(0.0, 1 - abs(x - mid) / (mid + 1)) ** 0.5 * rng.uniform(0.8, 1))
                   for x in range(cols)]
        for y in range(1, rows):
            below, row = heat[y - 1], heat[y]
            for x in range(cols):
                dst = x + rng.randrange(3) - 1
                if 0 <= dst < cols:
                    row[dst] = max(0, below[x] - rng.choice((0, 1, 1, 2)))
        if t >= 60:
            data = bytes(int(255 * (h / top) ** 1.5) for y in reversed(range(rows)) for h in heat[y])
            small = Image.frombytes("L", (cols, rows), data)
            frames.append(small.resize((round(cols * MM_X / 2), round(rows * MM_Y)), Image.Resampling.BILINEAR))
    return loop_crossfade(frames, overlap)

def draw_bonfire(img, d, x, g, flame):
    d.ellipse(box(x, g + 2, 22, 7), fill=80)                                              # ash mound
    d.line([(x - 18, g - 1), (x + 4, g - 6)], fill=110, width=3)                          # charred bones
    d.line([(x + 16, g - 1), (x - 2, g - 7)], fill=110, width=3)
    fx, fy = round(x - flame.width / 2), round(g - flame.height + 4)
    region = (fx, fy, fx + flame.width, fy + flame.height)
    img.paste(ImageChops.lighter(img.crop(region), flame), region)
    d.line([(x - 2, g + 2), (x + 4, g - 52)], fill=210, width=3)                          # coiled sword
    d.line([(x - 4, g - 46), (x + 11, g - 48)], fill=210, width=3)

def limb(d, pts, width, level):
    """A line with a dark border, so limbs stay separate from the body behind them."""
    d.line(pts, fill=0, width=width + 4, joint="curve")
    d.line(pts, fill=level, width=width, joint="curve")

def draw_solaire(d, x, g, praise, breath):
    """Solaire facing out; praise 0 is standing at ease, 1 is the full Praise the Sun pose."""
    lean = 6 * praise                       # arches back into the pose
    spread = 5 * praise
    for side in (-1, 1):                                                                  # legs and boots
        hip, foot = (x + side * 6, g - 36), (x + side * (10 + spread), g - 3)
        limb(d, [hip, (lerp(hip[0], foot[0], 0.5) + side, g - 18), foot], 6, 140)
        d.rectangle((foot[0] - 4, g - 7, foot[0] + 4, g), fill=210)
    top = g - 84 - lean - breath
    torso = [(x - 16, top), (x + 16, top), (x + 10, g - 38), (x - 10, g - 38)]
    d.polygon(torso, fill=45, outline=210, width=2)                                       # tabard
    d.polygon([(x - 11, g - 38), (x + 11, g - 38), (x + 13, g - 25), (x - 13, g - 25)],
              fill=120, outline=0, width=1)                                               # mail skirt
    d.line([(x - 11, g - 39), (x + 11, g - 39)], fill=230, width=3)                       # belt
    ex, ey = x, g - 62 - lean
    for k in range(8):                                                                    # sun emblem
        a = TAU * k / 8
        d.line([(ex, ey), (ex + 9 * math.cos(a), ey + 9 * math.sin(a))], fill=200, width=2)
    d.ellipse(box(ex, ey, 5), fill=255)
    for side in (-1, 1):                                                                  # arms
        sx, sy = x + side * 18, top + 3
        rest_hand = (x + side * 24, g - 46)
        up_hand = (x + side * 40, g - 136)
        hand = (lerp(rest_hand[0], up_hand[0], praise), lerp(rest_hand[1], up_hand[1], praise))
        elbow = (lerp(sx, hand[0], 0.5) + side * 6 * (1 - praise), lerp(sy, hand[1], 0.5))
        limb(d, [(sx, sy), elbow, hand], 5, 165)
        d.ellipse(box(*hand, 4), fill=230, outline=0, width=1)                            # gauntlet
        d.ellipse(box(sx, sy, 7, 5), fill=200, outline=0, width=2)                        # pauldron
    hy = top - 3
    d.rectangle((x - 11, hy - 28, x + 11, hy + 2), fill=0)                                # gap at the neck
    d.rectangle((x - 9, hy - 26, x + 9, hy), fill=175, outline=235, width=2)             # bucket helm
    d.line([(x - 9, hy - 16), (x + 9, hy - 16)], fill=0, width=2)                         # visor slit
    d.line([(x, hy - 15), (x, hy - 3)], fill=40, width=2)

def praise_the_sun():
    """Laid out for the lid turned 180 degrees (cut corner bottom right), then rotated back."""
    n = 170
    rng = random.Random(31)
    solaire_x, g = 52, 171
    fire_x, ledge = 122, 121              # the bonfire sits on a rock ledge above the cut corner
    flames = fire_layers(n, 16, 16, 30, seed=5, top=30)
    embers = [(int(k * n / 14 + rng.uniform(0, 8)), rng.uniform(-8, 8), rng.uniform(-0.6, 0.6))
              for k in range(14)]
    frames = []
    for t in range(n):
        praise = ease((t - 40) / 14) * (1 - ease((t - 112) / 14))
        sun = ease((t - 48) / 22) * (1 - ease((t - 112) / 20))
        flare = math.exp(-max(0, t - 66) / 5) * ease((t - 60) / 6)
        img, d = new_canvas(55 * flare)
        if sun > 0:
            sx, sy = solaire_x, lerp(-30, 24, sun)
            spin = t * 0.04
            for k in range(16):
                a = spin + TAU * k / 16
                length = 60 + 25 * (k % 2) + 60 * flare
                d.line([(sx + 18 * math.cos(a), sy + 18 * math.sin(a)),
                        (sx + length * math.cos(a), sy + length * math.sin(a))],
                       fill=int(sun * (70 + 90 * flare)), width=4)
            d.ellipse(box(sx, sy, 15), fill=int(sun * 140))
            d.ellipse(box(sx, sy, 11), fill=int(sun * 255))
        d.polygon([(0, H), (0, 170), (68, 170), (80, 150), (92, ledge), (W, ledge), (W, H)], fill=40)
        d.ellipse(box(fire_x, ledge + 2, 46, 7), fill=60)                                 # firelight
        draw_bonfire(img, d, fire_x, ledge, flames[t])
        sparks = []
        for t0, ox, drift in embers:
            age = (t - t0) % n
            if age < 30:
                sparks.append((fire_x + ox + drift * age + 3 * math.sin(age * 0.4),
                               ledge - 50 - age * 3.2, 1.8, 230 * (1 - age / 30)))
        draw_particles(d, sparks)
        draw_solaire(d, solaire_x, g, praise, 1.5 * cycle(t, n, 5))
        frames.append(img.transpose(Image.Transpose.ROTATE_180))
    return frames

def draw_z(d, x, y, size, level):
    s = size / 2
    d.line([(x - s, y - s), (x + s, y - s), (x - s, y + s), (x + s, y + s)], fill=int(level), width=3)

def draw_siegmeyer(d, x, g, nod, look, breath):
    """Siegmeyer of Catarina sitting on the ground; nod 1 is head slumped, look turns it sideways."""
    d.line([(x - 52, g + 2), (x - 40, g - 86)], fill=190, width=4)                        # zweihander
    d.line([(x - 52, g - 70), (x - 30, g - 66)], fill=190, width=4)
    d.line([(x - 40, g - 86), (x - 38, g - 100)], fill=130, width=3)
    d.ellipse(box(x - 22, g - 8, 17, 8), fill=90, outline=190, width=2)                   # legs
    d.ellipse(box(x + 22, g - 8, 17, 8), fill=90, outline=190, width=2)
    d.ellipse(box(x, g - 34, 28, 24 + breath), fill=55, outline=205, width=2)            # onion armour
    for k in (-14, 0, 14):
        d.arc(box(x + k * 0.6, g - 34, abs(k) + 3, 22 + breath), 250 if k < 0 else -70,
              110 if k < 0 else 70, fill=130, width=2)
    d.line([(x - 26, g - 44), (x - 40, g - 70)], fill=150, width=6)                       # arm on sword
    hx, hy = x + look * 5 + nod * 2, g - 66 + nod * 8 - breath
    d.ellipse(box(hx, hy, 19, 15), fill=175, outline=225, width=2)                        # onion helmet
    d.polygon([(hx - 9, hy - 10), (hx + 9, hy - 10), (hx + 1, hy - 28)], fill=175)
    d.line([(hx - 15 + look * 3, hy + 2), (hx + 15 + look * 3, hy + 2)], fill=20, width=2)  # visor
    d.line([(hx, hy - 14), (hx, hy + 13)], fill=110, width=2)

def siegmeyer_napping():
    n = 200
    x, g = 168, 171
    wake, asleep = 120, 176
    z_spawns = [0, 25, 50, 75, 100, 180]
    frames = []
    for t in range(n):
        img, d = new_canvas()
        d.polygon([(0, H), (0, 170), (W, 170), (W, H)], fill=35)
        awake = wake <= t < asleep
        if awake:
            nod = -0.6 * (1 - ease((t - wake) / 3)) if t < wake + 3 else 0.0
            nod += ease((t - 152) / 24)
            look = math.sin((t - wake - 6) * 0.25) * ease((t - wake - 6) / 4) * (1 - ease((t - 140) / 6))
        else:
            nod, look = 1.0, 0.0
        breath = 1.5 * cycle(t, n, 4) if not awake else 0.5 * cycle(t, n, 12)
        draw_siegmeyer(d, x, g, nod, look, breath)
        if awake and t < wake + 12:                                                       # startled "!"
            d.line([(x + 4, g - 120), (x + 4, g - 106)], fill=255, width=4)
            d.ellipse(box(x + 4, g - 100, 2.5), fill=255)
        for t0 in z_spawns:
            age = (t - t0) % n
            if age >= 60 or (wake <= t and (t0 < wake or t < t0) and t < asleep):
                continue          # the Z's pop when he wakes
            k = age / 60
            fade = min(1.0, age / 6) * (1 - k ** 2)
            draw_z(d, x + 24 + 42 * k + 5 * math.sin(age * 0.2), g - 100 - 80 * k, 17 + 10 * k, 230 * fade)
        frames.append(img)
    return frames

SCENES = {
    "Wizard vs Dragon": (wizard_vs_dragon, 50),
    "Hyperspace": (hyperspace, 40),
    "Digital Rain": (digital_rain, 50),
    "Inferno": (inferno, 50),
    "Thunderstorm": (thunderstorm, 50),
    "Space Battle": (space_battle, 45),
    "Heartbeat": (heartbeat, 40),
    "Plasma": (plasma, 50),
    "Ripples": (ripples, 50),
    "Equalizer": (equalizer, 45),
    "Praise the Sun": (praise_the_sun, 50),
    "Siegmeyer Napping": (siegmeyer_napping, 50),
}

if __name__ == "__main__":
    for name in sys.argv[1:] or SCENES:
        make, ms = SCENES[name]
        save(name, make(), ms)
