#!/usr/bin/env python3
"""Make period-sounding recordings for PIS-2 from a JSON script.

Voices come from macOS speech synthesis (`say`) or from your own recorded
WAV files. Speech is humanized (phrase-by-phrase pitch, pace and loudness
changes, irregular pauses, breaths, mouth noise, slow pitch and level drift)
and placed in a room with the other sounds of the scene: coughs, sighs,
cups, chairs, paper, doors, clocks, refrigerators, traffic. The mix then goes
through a tape chain (irregular wow and flutter, band limiting, hiss that
breathes, mains hum, crackle, dropouts, saturation, a tape stop at the end)
and is written as 11 kHz 8-bit mono WAV.

    python3 tools/make_audio.py tools/audio/aud-62-004.json
    python3 tools/make_audio.py tools/audio/*.json

Output goes to static/audio/<out>. Standard library only. `say` and
`afconvert` are macOS tools; elsewhere use "file" segments only (16-bit mono
WAV at 22050 Hz). If Premium or Enhanced voices are installed (System
Settings > Accessibility > Spoken Content), list them first in "voices" and
they will be used automatically.

See tools/audio/README.md for the script format.
"""

import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "static", "audio")
SR = 22050
OUT_SR = 11025
TAU = 2 * math.pi

STYLES = {
    #            hp    lp    wow    flut   hiss   hum    drive crackle drops
    "reel":     (100, 5200, .0028, .0007, .016, .004, 1.5, 0.15, 2),
    "cassette": (160, 4200, .0040, .0014, .024, .003, 1.8, 0.10, 4),
    "intercom": (300, 3300, .0010, .0004, .020, .010, 2.2, 0.05, 1),
    "radio":    (420, 2600, .0006, .0003, .045, .003, 3.0, 0.00, 0),
    "line":     (60,  3000, .0005, .0002, .018, .020, 1.2, 0.30, 0),
}


# ==========================================================================
# DSP helpers
# ==========================================================================

def lp1(x, fc):
    a = 1 - math.exp(-TAU * fc / SR)
    y, out = 0.0, []
    for v in x:
        y += a * (v - y)
        out.append(y)
    return out


def hp1(x, fc):
    rc = 1 / (TAU * fc)
    a = rc / (rc + 1.0 / SR)
    y, prev, out = 0.0, 0.0, []
    for v in x:
        y = a * (y + v - prev)
        prev = v
        out.append(y)
    return out


def biquad(x, kind, f, q=0.707):
    f = min(f, SR * 0.45)
    w = TAU * f / SR
    cs, sn = math.cos(w), math.sin(w)
    al = sn / (2 * q)
    if kind == "lp":
        b0, b1, b2 = (1 - cs) / 2, 1 - cs, (1 - cs) / 2
    elif kind == "hp":
        b0, b1, b2 = (1 + cs) / 2, -(1 + cs), (1 + cs) / 2
    else:  # band-pass, 0 dB peak
        b0, b1, b2 = al, 0.0, -al
    a0, a1, a2 = 1 + al, -2 * cs, 1 - al
    b0, b1, b2, a1, a2 = b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0
    x1 = x2 = y1 = y2 = 0.0
    out = []
    for v in x:
        y = b0 * v + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, v, y1, y
        out.append(y)
    return out


def noise(n, rng):
    g = rng.gauss
    return [g(0, 1) for _ in range(n)]


def norm(x, peak=1.0):
    m = max((abs(v) for v in x), default=0.0)
    return [v / m * peak for v in x] if m > 1e-9 else x


def smooth(n, rng, speed=0.5, parts=3):
    """Slow random curve in [-1, 1], n samples long."""
    comps = [(rng.uniform(0.3, 1.0) * speed, rng.uniform(0, TAU), rng.uniform(0.4, 1.0)) for _ in range(parts)]
    tot = sum(c[2] for c in comps)
    out = []
    for i in range(n):
        t = i / SR
        out.append(sum(a * math.sin(TAU * f * t + p) for f, p, a in comps) / tot)
    return out


def resample(x, factor):
    """factor > 1 raises pitch and shortens."""
    if abs(factor - 1) < 1e-6:
        return list(x)
    if factor > 1:
        x = lp1(lp1(x, SR * 0.45 / factor), SR * 0.45 / factor)
    n = int(len(x) / factor)
    last = len(x) - 1
    out = []
    for i in range(n):
        p = i * factor
        j = int(p)
        f = p - j
        out.append(x[j] * (1 - f) + x[min(j + 1, last)] * f)
    return out


def vary(x, curve, depth):
    """Time-varying resample: pitch and pace drift by depth * curve."""
    out, pos, last = [], 0.0, len(x) - 1
    i = 0
    while pos < last:
        j = int(pos)
        f = pos - j
        out.append(x[j] * (1 - f) + x[j + 1] * f)
        pos += 1 + depth * curve[min(i, len(curve) - 1)]
        i += 1
    return out


def decay_sine(n, f, tau, amp, phase=0.0):
    k = TAU * f / SR
    return [amp * math.exp(-i / (SR * tau)) * math.sin(k * i + phase) for i in range(n)]


def add(dst, src, pos, gain=1.0):
    pos = max(0, int(pos))
    need = pos + len(src)
    if need > len(dst):
        dst.extend([0.0] * (need - len(dst)))
    for i, v in enumerate(src):
        dst[pos + i] += v * gain


def sec(n):
    return int(SR * n)


# ==========================================================================
# Human sounds (nonverbal)
# ==========================================================================

def glottal(n, f0, rng, fall=0.15):
    """Low buzzy voicing for coughs, sighs and throat clearing."""
    out, ph = [], 0.0
    for i in range(n):
        f = f0 * (1 - fall * i / max(1, n)) * (1 + 0.02 * rng.uniform(-1, 1))
        ph += f / SR
        out.append(2 * (ph % 1.0) - 1)
    return lp1(lp1(out, 900), 900)


def breath(rng, f0=None, inhale=True):
    d = rng.uniform(0.28, 0.5) if inhale else rng.uniform(0.6, 1.1)
    n = sec(d)
    nz = noise(n, rng)
    c = rng.uniform(1100, 1700) if inhale else rng.uniform(600, 900)
    x = [a + 0.5 * b for a, b in zip(biquad(nz, "bp", c, 0.6), hp1(nz, 2500))]
    out = []
    for i, v in enumerate(x):
        t = i / n
        e = math.sin(math.pi * t) ** 1.4 if inhale else (min(1, t * 8) * (1 - t) ** 1.6)
        out.append(v * e)
    if not inhale and f0:
        g = glottal(n, f0 * 0.8, rng, 0.25)
        out = [v + 0.25 * gv * min(1, i / (n * 0.1)) * (1 - i / n) ** 2 for i, (v, gv) in enumerate(zip(out, g))]
    return norm(out, 0.12 if inhale else 0.16)


def cough(rng, f0=120):
    out = []
    count = rng.choice([1, 2, 2, 3])
    for k in range(count):
        d = rng.uniform(0.15, 0.24) * (0.85 ** k)
        n = sec(d)
        nz = noise(n, rng)
        body = [0.9 * a + 0.5 * b + 0.15 * c for a, b, c in
                zip(biquad(nz, "bp", rng.uniform(350, 520), 1.3), biquad(nz, "bp", rng.uniform(1100, 1800), 1.6), hp1(nz, 2600))]
        voc = glottal(n, f0 * rng.uniform(0.9, 1.15), rng, 0.3)
        seg = []
        for i in range(n):
            t = i / SR
            e = min(1, t / 0.004) * (math.exp(-t / 0.045) * 0.85 + 0.15 * math.exp(-t / 0.15))
            seg.append(e * body[i] + 0.4 * e * voc[i])
        seg = norm(seg, 0.9 * (0.8 ** k))
        out += seg + [0.0] * sec(rng.uniform(0.05, 0.13))
    return out


def throat(rng, f0=110):
    out = []
    for k in range(rng.choice([1, 2])):
        n = sec(rng.uniform(0.25, 0.4))
        nz = biquad(noise(n, rng), "bp", rng.uniform(450, 800), 1.2)
        g = glottal(n, f0 * 0.7, rng, 0.1)
        am = rng.uniform(22, 34)
        seg = [(0.6 * a + 0.5 * b) * (0.55 + 0.45 * (1 if math.sin(TAU * am * i / SR) > 0 else -1) * 0.6)
               * math.sin(math.pi * i / n) for i, (a, b) in enumerate(zip(nz, g))]
        out += norm(seg, 0.5) + [0.0] * sec(0.08)
    return out


def sniff(rng):
    out = []
    for _ in range(rng.choice([1, 2])):
        n = sec(rng.uniform(0.12, 0.22))
        x = hp1(noise(n, rng), 1800)
        out += [v * math.sin(math.pi * i / n) ** 2 for i, v in enumerate(x)] + [0.0] * sec(0.07)
    return norm(out, 0.14)


def lips(rng):
    out = [0.0] * sec(0.06)
    for p in (0, sec(rng.uniform(0.015, 0.035))):
        c = biquad([1.0] + [0.0] * sec(0.01), "bp", rng.uniform(1800, 3500), 4)
        add(out, c, p)
    return norm(out, 0.08)


HUMAN = {"cough": cough, "throat": throat, "sniff": lambda r, f0=None: sniff(r), "lips": lambda r, f0=None: lips(r),
         "breath": lambda r, f0=None: breath(r, f0, True), "sigh": lambda r, f0=None: breath(r, f0, False)}


# ==========================================================================
# Room sounds (foley)
# ==========================================================================

def impact(rng, bright=4000):
    return biquad([1.0] + [0.0] * sec(0.004), "bp", bright, 0.8)


def cup(rng):
    n = sec(0.35)
    out = [0.0] * n
    add(out, impact(rng, 3500), 0, 0.6)
    f1 = rng.uniform(160, 210)
    add(out, decay_sine(n, f1, 0.02, 0.8), 0)
    add(out, decay_sine(n, f1 * rng.uniform(2.2, 2.6), 0.015, 0.4), 0)
    for f in (rng.uniform(2100, 2600), rng.uniform(3500, 4200), rng.uniform(5200, 6200)):
        add(out, decay_sine(n, f, rng.uniform(0.05, 0.11), rng.uniform(0.08, 0.18)), 0)
    settle = sec(rng.uniform(0.025, 0.06))
    add(out, decay_sine(sec(0.08), f1 * 1.05, 0.012, 0.35), settle)
    add(out, impact(rng, 3000), settle, 0.25)
    return norm(out, 1.0)


def token(rng):
    n = sec(0.45)
    out = [0.0] * n
    hits = [0, sec(rng.uniform(0.04, 0.08))] + ([sec(rng.uniform(0.11, 0.16))] if rng.random() < 0.6 else [])
    for k, p in enumerate(hits):
        g = 0.65 ** k
        add(out, impact(rng, 5000), p, 0.5 * g)
        for f in (rng.uniform(2900, 3600), rng.uniform(4600, 5400), rng.uniform(6800, 7800)):
            add(out, decay_sine(sec(0.3), f, rng.uniform(0.06, 0.14), 0.25 * g), p)
    return norm(out, 1.0)


def stick_slip(rng, dur, rate_lo, rate_hi, res, q, grain=0.006):
    n = sec(dur)
    pulses = [0.0] * n
    t, curve = 0.0, smooth(n, rng, 1.5)
    while t < dur:
        i = int(t * SR)
        if i >= n:
            break
        pulses[i] = rng.uniform(0.4, 1.0)
        r = rate_lo + (rate_hi - rate_lo) * (0.5 + 0.5 * curve[i])
        t += (1.0 / r) * rng.uniform(0.7, 1.3)
    body = [0.0] * n
    for f in res:
        b = biquad(pulses, "bp", f * rng.uniform(0.9, 1.1), q)
        body = [a + c for a, c in zip(body, b)]
    env = smooth(n, rng, 2.0)
    return [v * (0.6 + 0.4 * e) * math.sin(math.pi * i / n) ** 0.5 for i, (v, e) in enumerate(zip(body, env))]


def chair_creak(rng):
    return norm(stick_slip(rng, rng.uniform(0.5, 1.1), 9, 30, [rng.uniform(500, 1100), rng.uniform(1600, 2300)], 9), 1.0)


def chair_scrape(rng):
    d = rng.uniform(0.35, 0.8)
    s = stick_slip(rng, d, 60, 170, [rng.uniform(250, 450), rng.uniform(700, 1000), rng.uniform(1500, 2200)], 5)
    fr = hp1(noise(len(s), rng), 1200)
    return norm([a + 0.08 * b * math.sin(math.pi * i / len(s)) for i, (a, b) in enumerate(zip(s, fr))], 1.0)


def chair_roll(rng):
    n = sec(rng.uniform(0.6, 1.0))
    rum = lp1(lp1(noise(n, rng), 300), 300)
    out = [v * math.sin(math.pi * i / n) for i, v in enumerate(rum)]
    p = 0
    while p < n:
        add(out, impact(rng, 1800), p, 0.15)
        p += sec(rng.uniform(0.09, 0.14))
    return norm(out, 1.0)


def paper(rng):
    d = rng.uniform(0.5, 1.4)
    n = sec(d)
    out = [0.0] * n
    for _ in range(int(d * rng.uniform(25, 50))):
        ln = sec(rng.uniform(0.002, 0.018))
        b = hp1(noise(ln, rng), 1500)
        add(out, [v * math.sin(math.pi * i / ln) for i, v in enumerate(b)], rng.randrange(0, n), math.exp(rng.gauss(-1, 0.6)))
    return norm(out, 1.0)


def pen(rng):
    d = rng.uniform(1.0, 2.2)
    n = sec(d)
    x = biquad(noise(n, rng), "bp", rng.uniform(3000, 4500), 1.0)
    out, t = [0.0] * n, 0.0
    env = [0.0] * n
    while t < d:
        ln = rng.uniform(0.08, 0.25)
        a, b = int(t * SR), min(n, int((t + ln) * SR))
        for i in range(a, b):
            env[i] = math.sin(math.pi * (i - a) / max(1, b - a)) * rng.uniform(0.7, 1.0)
        t += ln + rng.uniform(0.02, 0.15)
    return norm([v * e for v, e in zip(x, env)], 1.0)


def rustle(rng):
    n = sec(rng.uniform(0.4, 1.0))
    x = lp1(biquad(noise(n, rng), "bp", rng.uniform(500, 1200), 0.7), 2500)
    c = smooth(n, rng, 6.0)
    return norm([v * max(0, c[i]) ** 2 * math.sin(math.pi * i / n) for i, v in enumerate(x)], 1.0)


def step(rng, light=False):
    n = sec(0.2)
    out = [0.0] * n
    add(out, decay_sine(n, rng.uniform(70, 110) * (1.6 if light else 1), 0.03, 1.0), 0)
    add(out, lp1(noise(sec(0.03), rng), 1500), 0, 0.3)
    add(out, decay_sine(n, rng.uniform(150, 220), 0.02, 0.4), sec(rng.uniform(0.05, 0.09)))
    return norm(out, 1.0)


def steps(rng, count=4, light=False):
    out = []
    for k in range(count):
        add(out, step(rng, light), sec(k * (0.36 if light else 0.52) * rng.uniform(0.9, 1.1)), 0.5 + 0.5 * (k + 1) / count)
    return norm(out, 1.0)


def latch(rng):
    n = sec(0.12)
    out = [0.0] * n
    add(out, impact(rng, 4000), 0, 0.6)
    add(out, decay_sine(n, rng.uniform(2200, 2900), 0.02, 0.4), 0)
    add(out, impact(rng, 3000), sec(0.03), 0.4)
    return norm(out, 1.0)


def door_open(rng):
    out = latch(rng)
    add(out, stick_slip(rng, rng.uniform(0.4, 0.7), 15, 40, [rng.uniform(800, 1400)], 12), sec(0.08), 0.5)
    return norm(out, 1.0)


def door_close(rng):
    n = sec(0.4)
    out = [0.0] * n
    add(out, decay_sine(n, rng.uniform(70, 95), 0.07, 1.0), 0)
    add(out, lp1(noise(sec(0.04), rng), 800), 0, 0.5)
    add(out, latch(rng), sec(0.01), 0.5)
    return norm(out, 1.0)


def clunk(rng):
    n = sec(0.25)
    out = [math.sin(TAU * 70 * i / SR) * 0.5 * math.exp(-i / (SR * 0.04)) for i in range(n)]
    add(out, lp1(noise(sec(0.02), rng), 2000), 0, 0.3)
    return norm(out, 1.0)


def click(rng):
    n = sec(0.03)
    out = [0.0] * n
    add(out, impact(rng, 3000), 0, 1.0)
    return norm(out, 1.0)


def squelch(rng):
    n = sec(0.22)
    return [rng.uniform(-1, 1) * 0.55 * (1 - i / n) for i in range(n)]


def relay(rng):
    n = sec(0.05)
    out = [0.0] * n
    add(out, impact(rng, 2500), 0, 1.0)
    add(out, impact(rng, 2000), sec(0.012), 0.6)
    return norm(out, 1.0)


def car(rng):
    d = rng.uniform(4.0, 6.5)
    n = sec(d)
    x = lp1(biquad(noise(n, rng), "bp", 300, 0.5), 1200)
    return norm([v * math.exp(-((i / n - 0.5) ** 2) / 0.04) for i, v in enumerate(x)], 1.0)


FOLEY = {"cup": cup, "token": token, "chair_creak": chair_creak, "chair_scrape": chair_scrape, "chair_roll": chair_roll,
         "paper": paper, "pen": pen, "rustle": rustle, "steps": steps, "latch": latch, "door_open": door_open,
         "door_close": door_close, "clunk": clunk, "click": click, "squelch": squelch, "relay": relay, "car": car}


# ==========================================================================
# Ambience beds
# ==========================================================================

def bed(kind, n, rng):
    if kind == "clock":
        out, t, k = [0.0] * n, rng.uniform(0, 1), 0
        while t * SR < n:
            c = [0.0] * sec(0.05)
            add(c, impact(rng, 3200 if k % 2 else 2700), 0, 1.0)
            add(c, decay_sine(len(c), 1200 if k % 2 else 1000, 0.008, 0.6), 0)
            add(out, c, t * SR, 1.0)
            t += 1.0 + rng.uniform(-0.004, 0.004)
            k += 1
        return out
    if kind in ("fridge", "equipment"):
        f = 60.0
        hum = [0.0] * n
        c = smooth(n, rng, 0.2)
        harm = [(1, 0.5), (2, 1.0), (3, 0.4), (4, 0.2)] if kind == "fridge" else [(1, 0.6), (2, 0.5), (3, 0.5), (5, 0.25)]
        for i in range(n):
            t = i / SR
            hum[i] = (1 + 0.15 * c[i]) * sum(a * math.sin(TAU * f * h * t) for h, a in harm)
        fan = lp1(lp1(noise(n, rng), 600 if kind == "fridge" else 1100), 900)
        out = [0.5 * h + 0.6 * v for h, v in zip(norm(hum), norm(fan))]
        if kind == "equipment":
            p = sec(rng.uniform(3, 8))
            while p < n:
                add(out, relay(rng), p, 0.6)
                p += sec(rng.uniform(5, 18))
        return out
    if kind == "traffic":
        out, p = [0.0] * n, sec(rng.uniform(5, 20))
        while p < n:
            add(out, car(rng), p, rng.uniform(0.5, 1.0))
            p += sec(rng.uniform(18, 40))
        return out[:n]
    if kind == "house":
        out, p = [0.0] * n, sec(rng.uniform(8, 20))
        while p < n:
            add(out, chair_creak(rng), p, rng.uniform(0.3, 0.6))
            p += sec(rng.uniform(15, 45))
        return out[:n]
    if kind == "room":
        return lp1(noise(n, rng), 400)
    raise SystemExit("unknown bed: %s" % kind)


# ==========================================================================
# Speech
# ==========================================================================

QUALITY = ("Premium", "Enhanced", "プレミアム", "拡張", "高品質")
_voices = None


def installed_voices():
    global _voices
    if _voices is None:
        _voices = []
        listing = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
        for line in listing.splitlines():
            head = line.split("#")[0].rstrip()
            parts = head.rsplit(None, 1)
            if len(parts) == 2:
                full = parts[0].strip()
                base = re.split(r" \(|（", full)[0].strip()
                _voices.append((full, base, parts[1].strip()))
    return _voices


def resolve_voice(names, locale):
    vs = installed_voices()
    for name in names:
        cands = [v for v in vs if v[1] == name and v[2] == locale] or [v for v in vs if v[1] == name]
        if cands:
            return max(cands, key=lambda v: any(q in v[0] for q in QUALITY))[0]
    raise SystemExit("none of these voices is installed: %s" % ", ".join(names))


def read_wav_any(path):
    src, tmp = path, None
    with wave.open(path, "rb") as w:
        ok = w.getframerate() == SR and w.getsampwidth() == 2 and w.getnchannels() == 1
    if not ok:
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@%d" % SR, "-c", "1", path, tmp], check=True)
        src = tmp
    with wave.open(src, "rb") as w:
        raw = w.readframes(w.getnframes())
    if tmp:
        os.unlink(tmp)
    vals = memoryview(raw).cast("h")
    return [v / 32768.0 for v in vals]


def trim(x, thr=0.004):
    a = next((i for i, v in enumerate(x) if abs(v) > thr), 0)
    b = len(x) - next((i for i, v in enumerate(reversed(x)) if abs(v) > thr), 0)
    return x[max(0, a - 150):min(len(x), b + 300)]


def humanize(text, rng, vol):
    """Turn script text into `say` text with phrase-level prosody changes.

    Markup:  *word* emphasis   _words_ quiet   ... long hesitation
             -- break (false start)   [[...]] passed through unchanged
    """
    def emph(s):
        s = re.sub(r"\*([^*]+)\*", lambda m: "[[pbas +4]][[volm %.2f]][[rate -18]]%s[[rate +18]][[volm %.2f]][[pbas -4]]"
                   % (min(1.0, vol * 1.25), m.group(1), vol), s)
        return re.sub(r"_([^_]+)_", lambda m: "[[volm %.2f]]%s[[volm %.2f]]" % (vol * 0.55, m.group(1), vol), s)

    out = ["[[volm %.2f]]" % vol]
    for part in re.split(r"(\.\.\.|--|[,;:.?!])", text):
        if part in (",", ";", ":"):
            out.append(part + "[[slnc %d]]" % rng.randint(30, 200))
        elif part in (".", "?", "!"):
            out.append(part + "[[slnc %d]]" % rng.randint(60, 300))
        elif part == "...":
            out.append("[[slnc %d]]" % rng.randint(350, 750))
        elif part == "--":
            out.append("[[slnc %d]]" % rng.randint(80, 200))
        elif part.strip():
            dp = rng.choice([-3, -2, -1, 0, 0, 1, 2, 3])
            dr = rng.randint(-14, 12)
            v = vol * rng.uniform(0.8, 1.0)
            out.append("[[pbas %+d]][[volm %.2f]][[rate %+d]]%s[[rate %+d]]" % (dp, v, dr, emph(part), -dr))
    return "".join(out)


def speak(text, spk, rng):
    if "file" in spk:
        return read_wav_any(spk["file"])
    voice = spk["_voice"]
    shift = spk.get("shift", 1.0)
    rate = int(spk.get("rate", 170) / shift)
    d = tempfile.mkdtemp()
    aiff, wav = os.path.join(d, "s.aiff"), os.path.join(d, "s.wav")
    said = humanize(text, rng, spk.get("vol", 0.85)) if spk.get("humanize", True) else text
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", aiff, said], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@%d" % SR, "-c", "1", aiff, wav], check=True)
    x = read_wav_any(wav)
    for p in (aiff, wav):
        os.unlink(p)
    os.rmdir(d)
    x = trim(x)
    x = resample(x, shift * rng.uniform(0.985, 1.015))
    x = vary(x, smooth(len(x) + SR, rng, 0.8), spk.get("drift", 0.012))
    lvl = smooth(len(x), rng, 0.9)
    x = [v * (1 + 0.14 * c) for v, c in zip(x, lvl)]
    return norm(x, 0.55)


# ==========================================================================
# Room and tape
# ==========================================================================

def place_prep(clip, dist):
    fc = 7500 - 4800 * dist
    return lp1(lp1(clip, fc), fc)


def reverb(x, size, rng):
    n = len(x)
    er = [0.0] * n
    for t, g in [(0.007, 0.5), (0.011, 0.42), (0.017, 0.34), (0.023, 0.28), (0.031, 0.2), (0.042, 0.14)]:
        d = int(SR * t * size)
        for i in range(d, n):
            er[i] += x[i - d] * g
    out = [0.0] * n
    for t, fb in [(0.0297, 0.70), (0.0371, 0.68), (0.0411, 0.66), (0.0437, 0.64)]:
        d = max(1, int(SR * t * size))
        buf = [0.0] * d
        lpv, k = 0.0, 0
        for i in range(n):
            y = buf[k]
            lpv += 0.45 * (y - lpv)
            buf[k] = x[i] + lpv * fb
            out[i] += y
            k = (k + 1) % d
    for t, g in [(0.005, 0.6), (0.0017, 0.6)]:
        d = max(1, int(SR * t))
        buf = [0.0] * d
        k = 0
        res = []
        for v in out:
            b = buf[k]
            y = -g * v + b
            buf[k] = v + g * y
            res.append(y)
            k = (k + 1) % d
        out = res
    return [a + 0.25 * b for a, b in zip(er, out)]


def tape(x, style, rng, stop=False):
    hp, lp, wow, flut, hiss, hum, drive, crackle, drops = STYLES[style]
    n = len(x)
    wcurve = smooth(n + SR, rng, 0.6, 4)
    fl = []
    ff, ph = rng.uniform(6.5, 8.5), 0.0
    for i in range(n + SR):
        ph += (ff + 0.6 * wcurve[i]) / SR
        fl.append(wow / max(flut, 1e-9) * wcurve[i] + math.sin(TAU * ph))
    x = vary(x, fl, flut)
    if stop:
        # the transport is stopped: speed falls to nothing over ~0.5 s
        k = sec(0.5)
        tail, head = x[-k:], x[:-k]
        out, pos = [], 0.0
        for u in range(k):
            j = min(int(pos), len(tail) - 2)
            f = pos - int(pos)
            out.append((tail[j] * (1 - f) + tail[j + 1] * f) * (1 - u / k) ** 0.6)
            pos += 1 - 0.95 * (u / k)
        x = head + out
    x = hp1(x, hp)
    x = lp1(lp1(x, lp), lp)
    peak = max((abs(v) for v in x), default=0)
    if peak > 0.2:
        x = [v / peak * 0.8 for v in x]
    n = len(x)
    nz = lp1(noise(n, rng), 5200)
    nmax = max(abs(v) for v in nz) / 3.0
    breathe = smooth(n, rng, 0.3)
    hd = smooth(n, rng, 0.15)
    p = rng.uniform(0, TAU)
    out = []
    for i, v in enumerate(x):
        t = i / SR
        h = hum * (1 + 0.2 * hd[i]) * (math.sin(TAU * 60 * t + p) + 0.5 * math.sin(TAU * 180 * t))
        out.append(v + hiss * (1 + 0.3 * breathe[i]) * nz[i] / nmax + h)
    if crackle:
        for _ in range(int(n / SR * crackle * rng.uniform(0.5, 1.5))):
            add(out, hp1([rng.uniform(-1, 1) for _ in range(sec(0.002))], 1500), rng.randrange(0, n), rng.uniform(0.02, 0.08))
        out = out[:n]
    for _ in range(drops):
        c = rng.randrange(0, n)
        w = sec(rng.uniform(0.03, 0.15))
        depth = rng.uniform(0.3, 0.7)
        for i in range(max(0, c - w), min(n, c + w)):
            out[i] *= (1 - depth) + depth * abs(i - c) / w
    k = math.tanh(drive)
    out = [math.tanh(drive * v) / k for v in out]
    peak = max(abs(v) for v in out)
    level = 0.5 if style == "line" else 0.88
    return [v / peak * level for v in out]


def write_8bit(x, path):
    y = [(x[i] + x[i + 1]) * 0.5 for i in range(0, len(x) - 1, 2)]
    data = bytes(max(0, min(255, int(round(128 + 127 * v)))) for v in y)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(OUT_SR)
        w.writeframes(data)


# ==========================================================================
# Timeline
# ==========================================================================

def build(script_path):
    with open(script_path, encoding="utf-8") as f:
        sc = json.load(f)
    rng = random.Random(sc.get("seed", 1))
    style = sc.get("style", "reel")
    room = sc.get("room", {"size": 0.8, "wet": 0.2})
    speakers = sc.get("speakers", {})
    base = os.path.dirname(script_path)
    for name, spk in speakers.items():
        if "file" in spk:
            spk["file"] = os.path.join(base, spk["file"])
        else:
            spk["_voice"] = resolve_voice(spk["voices"], spk.get("locale", "en_US"))
            print("  %-6s -> %s" % (name, spk["_voice"]))

    dry, wet = [], []
    cursor = sec(sc.get("lead", 1.0))
    last_who = None

    def put(clip, at, dist, gain):
        c = place_prep(clip, dist)
        add(dry, c, at, gain * (1 - 0.5 * dist))
        add(wet, c, at, gain * room.get("wet", 0.2) * (0.3 + dist))

    for seg in sc["timeline"]:
        if isinstance(seg, list):
            seg = {"say": seg[0], "text": seg[1]}
        at = cursor + sec(seg.get("offset", 0))
        if "pause" in seg:
            cursor += sec(seg["pause"])
            continue
        if "say" in seg:
            who = seg["say"]
            spk = speakers[who]
            gap = seg.get("gap", rng.uniform(0.25, 0.65) if who != last_who else rng.uniform(0.12, 0.35))
            at += sec(gap)
            dist = seg.get("dist", spk.get("dist", 0.3))
            if seg.get("breath", len(seg["text"].split()) >= 4 and rng.random() < 0.5):
                b = breath(rng)
                put(b, at - len(b) + sec(0.05), dist, spk.get("breath_gain", 1.0))
            if rng.random() < 0.15:
                put(lips(rng), at - sec(0.08), dist, 1.0)
            clip = speak(seg["text"], spk, rng)
            if seg.get("cut"):
                clip = clip[:max(0, len(clip) - sec(seg["cut"]))]
            put(clip, at, dist, seg.get("gain", 1.0) * spk.get("gain", 1.0))
            end = at + len(clip)
            last_who = who
        elif "fx" in seg:
            spk = speakers.get(seg.get("who"), {})
            clip = HUMAN[seg["fx"]](rng, spk.get("f0", 120))
            at += sec(seg.get("gap", 0.15))
            put(clip, at, seg.get("dist", spk.get("dist", 0.3)), seg.get("gain", 1.0))
            end = at + len(clip)
        elif "sfx" in seg:
            fn = FOLEY[seg["sfx"]]
            clip = fn(rng, **seg.get("args", {}))
            at += sec(seg.get("gap", 0.1))
            put(clip, at, seg.get("dist", 0.4), seg.get("gain", 0.3))
            end = at + len(clip)
        else:
            raise SystemExit("bad segment: %r" % seg)
        if not seg.get("hold"):
            cursor = max(cursor, end)

    total = max(len(dry), cursor) + sec(sc.get("tail", 1.0))
    for buf in (dry, wet):
        buf.extend([0.0] * (total - len(buf)))
    for b in sc.get("beds", []):
        x = norm(bed(b["type"], total, rng), 1.0)
        d = b.get("dist", 0.6)
        put(x, 0, d, b.get("gain", 0.05))
    dry, wet = dry[:total], wet[:total]

    mix = [a + b for a, b in zip(dry, reverb(wet, room.get("size", 0.8), rng))]
    out = tape(mix, style, rng, stop=sc.get("stop", False))
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, sc["out"])
    write_8bit(out, path)
    print("%s  %.1f s  %d KB" % (os.path.relpath(path, ROOT), len(out) / SR, os.path.getsize(path) // 1024))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for p in sys.argv[1:]:
        build(p)
