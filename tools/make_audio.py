#!/usr/bin/env python3
"""Make period-sounding recordings for PIS-2 from a JSON script.

Voices come from macOS speech synthesis (`say`) or from your own recorded
WAV files. Everything is then run through a degradation chain (tape wow and
flutter, band limiting, hiss, mains hum, saturation, dropouts) and written as
11 kHz 8-bit mono WAV, which is what a 1996 dub to a PC would have produced.

    python3 tools/make_audio.py tools/audio/aud-62-004.json
    python3 tools/make_audio.py tools/audio/*.json

Output goes to static/audio/<out>. Standard library only. `say` and
`afconvert` are macOS tools; on other systems use "file" segments only
(16-bit mono WAV at 22050 Hz).

Script format (see tools/audio/ for examples):

    {
      "out": "aud-62-004.wav",
      "style": "reel",              reel | cassette | intercom | radio | line
      "seed": 62004,
      "lead": 1.5,                  seconds of noise before the first segment
      "tail": 1.0,
      "voices": {"INT": ["Reed", "en_US", 160]},
      "segments": [
        ["INT", "Mr. Pruitt, how many people ..."],
        {"pause": 0.8},
        {"speaker": "PRUITT", "text": "Fourteen.", "gain": 0.9},
        {"file": "my-recording.wav"},
        {"sfx": "squelch"},          squelch | click | clunk
        ...
      ]
    }
"""

import json
import math
import os
import random
import subprocess
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "static", "audio")
SR = 22050          # working rate
OUT_SR = 11025      # delivered rate

STYLES = {
    #            hp    lp    wow   flut  hiss   hum    drive dropouts
    "reel":     (110, 4800, .0030, .0008, .020, .006, 1.6, 2),
    "cassette": (180, 3800, .0045, .0015, .032, .004, 2.0, 5),
    "intercom": (320, 3200, .0010, .0004, .026, .012, 2.4, 1),
    "radio":    (420, 2600, .0006, .0003, .050, .003, 3.2, 0),
    "line":     (60,  3000, .0005, .0002, .018, .022, 1.2, 0),
}


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------

_voice_cache = None


def resolve_voice(name, locale):
    """Find the installed voice whose name starts with `name` for `locale`."""
    global _voice_cache
    if _voice_cache is None:
        listing = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
        _voice_cache = []
        for line in listing.splitlines():
            head = line.split("#")[0].rstrip()
            parts = head.rsplit(None, 1)
            if len(parts) == 2:
                _voice_cache.append((parts[0].strip(), parts[1].strip()))
    for full, loc in _voice_cache:
        if full.split(" (")[0] == name and loc == locale:
            return full
    for full, loc in _voice_cache:
        if full.split(" (")[0] == name:
            return full
    raise SystemExit("voice not installed: %s (%s)" % (name, locale))


def read_wav_any(path):
    """Read a WAV as floats at SR. Converts with afconvert when it can."""
    src = path
    tmp = None
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
    n = len(raw) // 2
    vals = memoryview(raw).cast("h")
    return [vals[i] / 32768.0 for i in range(n)]


def speak(text, voice, rate):
    d = tempfile.mkdtemp()
    aiff = os.path.join(d, "s.aiff")
    wav = os.path.join(d, "s.wav")
    subprocess.run(["say", "-v", voice, "-r", str(rate), "-o", aiff, text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@%d" % SR, "-c", "1", aiff, wav], check=True)
    out = read_wav_any(wav)
    os.unlink(aiff)
    os.unlink(wav)
    os.rmdir(d)
    # trim synthesis silence at both ends
    thr = 0.004
    a = next((i for i, v in enumerate(out) if abs(v) > thr), 0)
    b = len(out) - next((i for i, v in enumerate(reversed(out)) if abs(v) > thr), 0)
    return out[max(0, a - 200):min(len(out), b + 400)]


def sfx(kind, rng):
    if kind == "squelch":
        n = int(SR * 0.22)
        return [rng.uniform(-1, 1) * 0.55 * (1 - i / n) for i in range(n)]
    if kind == "click":
        n = int(SR * 0.03)
        return [(0.6 if i < 12 else 0) + rng.uniform(-1, 1) * 0.15 * (1 - i / n) for i in range(n)]
    if kind == "clunk":
        n = int(SR * 0.25)
        return [math.sin(2 * math.pi * 70 * i / SR) * 0.5 * math.exp(-i / (SR * 0.04))
                + rng.uniform(-1, 1) * 0.2 * math.exp(-i / (SR * 0.01)) for i in range(n)]
    raise SystemExit("unknown sfx: %s" % kind)


# --------------------------------------------------------------------------
# Processing
# --------------------------------------------------------------------------

def lowpass(x, fc):
    a = 1 - math.exp(-2 * math.pi * fc / SR)
    y, out = 0.0, []
    for v in x:
        y += a * (v - y)
        out.append(y)
    return out


def highpass(x, fc):
    rc = 1 / (2 * math.pi * fc)
    a = rc / (rc + 1.0 / SR)
    y, prev, out = 0.0, 0.0, []
    for v in x:
        y = a * (y + v - prev)
        prev = v
        out.append(y)
    return out


def wow_flutter(x, wow, flut, rng):
    out = []
    pos = 0.0
    p1, p2 = rng.uniform(0, 6.28), rng.uniform(0, 6.28)
    n = len(x)
    t = 0
    while pos < n - 1:
        i = int(pos)
        f = pos - i
        out.append(x[i] * (1 - f) + x[i + 1] * f)
        sec = t / SR
        pos += 1 + wow * math.sin(2 * math.pi * 0.55 * sec + p1) + flut * math.sin(2 * math.pi * 7.3 * sec + p2)
        t += 1
    return out


def offmic(x):
    x = lowpass(lowpass(x, 1800), 1800)
    d = int(SR * 0.045)
    return [0.5 * (x[i] + (0.45 * x[i - d] if i >= d else 0)) for i in range(len(x))]


def process(x, style, rng):
    hp, lp, wow, flut, hiss, hum, drive, drops = STYLES[style]
    x = wow_flutter(x, wow, flut, rng)
    x = highpass(x, hp)
    x = lowpass(lowpass(x, lp), lp)
    peak = max(1e-6, max(abs(v) for v in x))
    if peak > 0.2:  # a track with real content; leave near-silent tracks alone
        x = [v / peak * 0.8 for v in x]
    # noise floor: filtered hiss plus mains hum
    noise = lowpass([rng.gauss(0, 1) for _ in range(len(x))], 5200)
    nmax = max(1e-6, max(abs(v) for v in noise)) / 3.0
    p = rng.uniform(0, 6.28)
    out = []
    for i, v in enumerate(x):
        t = i / SR
        h = hum * (math.sin(2 * math.pi * 60 * t + p) + 0.5 * math.sin(2 * math.pi * 180 * t))
        out.append(v + hiss * noise[i] / nmax + h)
    # dropouts: brief dips in level, as on worn tape
    for _ in range(drops):
        c = rng.randrange(0, len(out))
        w = int(SR * rng.uniform(0.04, 0.12))
        for i in range(max(0, c - w), min(len(out), c + w)):
            out[i] *= 0.35 + 0.65 * abs(i - c) / w
    k = math.tanh(drive)
    out = [math.tanh(drive * v) / k for v in out]
    peak = max(1e-6, max(abs(v) for v in out))
    level = 0.5 if style == "line" else 0.88
    return [v / peak * level for v in out]


def write_8bit(x, path):
    # halve the rate: average pairs after the band limit above
    y = [(x[i] + x[i + 1]) * 0.5 for i in range(0, len(x) - 1, 2)]
    data = bytes(max(0, min(255, int(round(128 + 127 * v)))) for v in y)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(OUT_SR)
        w.writeframes(data)


# --------------------------------------------------------------------------

def build(script_path):
    with open(script_path, encoding="utf-8") as f:
        sc = json.load(f)
    rng = random.Random(sc.get("seed", 1))
    style = sc.get("style", "reel")
    voices = {k: (resolve_voice(v[0], v[1]), v[2]) for k, v in sc.get("voices", {}).items()}

    track = [0.0] * int(SR * sc.get("lead", 1.0))
    for seg in sc["segments"]:
        if isinstance(seg, list):
            seg = {"speaker": seg[0], "text": seg[1]}
        if "pause" in seg:
            track += [0.0] * int(SR * seg["pause"])
            continue
        if "sfx" in seg:
            g = seg.get("gain", 1.0)
            track += [v * g for v in sfx(seg["sfx"], rng)]
            continue
        if "file" in seg:
            clip = read_wav_any(os.path.join(os.path.dirname(script_path), seg["file"]))
        else:
            voice, rate = voices[seg["speaker"]]
            clip = speak(seg["text"], voice, seg.get("rate", rate))
        if seg.get("cut"):
            clip = clip[:max(0, len(clip) - int(SR * seg["cut"]))]
        if seg.get("offmic"):
            clip = offmic(clip)
        g = seg.get("gain", 1.0)
        track += [v * g for v in clip]
        track += [0.0] * int(SR * seg.get("after", 0.35))
    track += [0.0] * int(SR * sc.get("tail", 1.0))

    out = process(track, style, rng)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, sc["out"])
    write_8bit(out, path)
    print("%s  %.1f s  %d KB" % (os.path.relpath(path, ROOT), len(out) / SR, os.path.getsize(path) // 1024))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for p in sys.argv[1:]:
        build(p)
