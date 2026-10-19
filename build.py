#!/usr/bin/env python3
"""Build the PIS-2 // WICKER BASIN site.

Reads Markdown documents from content/ (English) and ja/content/ (Japanese),
renders them into 1990s-style HTML with templates/ and ja/templates/, copies
static/, and writes everything to _site/ (English) and _site/ja/ (Japanese).

Every page links to the same page in the other edition. A document that has
not been translated yet links to the other edition's index instead.

Standard library only (Python 3.8+).

    python3 build.py            # build, print warnings
    python3 build.py --strict   # build, exit 1 on broken links or duplicate ids
"""

import json
import os
import re
import shutil
import sys
import wave

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")
OUT = os.path.join(ROOT, "_site")

# Order of the generated Records index. Headings are per edition.
RECORD_KINDS = ["asset", "incident", "experiment", "analysis", "transcript", "log", "legacy"]

STRINGS = {
    "en": {
        "classification": "TOP SECRET // WICKER BASIN // NOFORN",
        "record_kinds": {
            "asset": "ASSET FILES",
            "incident": "INCIDENT REPORTS",
            "experiment": "EXPERIMENT AND PROGRAM REPORTS",
            "analysis": "ANALYSES",
            "transcript": "TRANSCRIPTS",
            "log": "LOGS, FORMS AND WORK ORDERS",
            "legacy": "J-4 LEGACY FILES (UNREVIEWED SCANS)",
        },
        "records_head": ("DOCUMENT", "DATE", "SUBJECT"),
        "audio_list_head": ("RECORDING", "FORMAT", "LENGTH", "FILED WITH"),
        "audio": "AUDIO",
        "audio_missing": "RECORDING NOT ON THIS SERVER. REQUEST FROM CUSTODIAL RECORDS.",
        "play": "PLAY",
        "stop": "STOP",
        "download": "Download .WAV",
        "fmt": "%d KHZ %d-BIT %s",
        "mono": "MONO",
        "stereo": "STEREO",
    },
    "ja": {
        "classification": "極秘 // WICKER BASIN // 外国人開示禁止",
        "record_kinds": {
            "asset": "資産ファイル",
            "incident": "事案報告",
            "experiment": "実験・計画報告",
            "analysis": "分析",
            "transcript": "聴取記録",
            "log": "記録簿・様式・作業指示",
            "legacy": "J-4 残存文書（未精査スキャン）",
        },
        "records_head": ("文書", "日付", "件名"),
        "audio_list_head": ("録音", "形式", "長さ", "添付先文書"),
        "audio": "音声",
        "audio_missing": "この録音は本サーバーに収録されていない。保管記録課に請求すること。",
        "play": "再生",
        "stop": "停止",
        "download": ".WAV をダウンロード",
        "fmt": "%dkHz %dビット %s",
        "mono": "モノラル",
        "stereo": "ステレオ",
    },
}

warnings = []


def warn(msg):
    warnings.append(msg)


# --------------------------------------------------------------------------
# Editions
# --------------------------------------------------------------------------

class Edition:
    """One language version of the site.

    base:   directory holding content/ and templates/, relative to ROOT
    out:    output directory, relative to _site/
    static: path from the edition's root to _site/static/
    """

    def __init__(self, lang, base, out, static, search_index):
        self.lang = lang
        self.content = os.path.join(ROOT, base, "content")
        self.templates_dir = os.path.join(ROOT, base, "templates")
        self.out = os.path.join(OUT, out)
        self.prefix = out + "/" if out else ""
        self.static = static
        self.search_index = search_index
        self.s = STRINGS[lang]
        self.other = None
        self.docs = []
        self.index = {}
        self.by_path = {}
        self.templates = {}
        self.audio_refs = []  # (doc, file, label, note) collected before rendering

    def alt_href(self, doc):
        """Link from doc to the same page in the other edition."""
        target = doc.rel_out if doc.rel_out in self.other.by_path else "index.html"
        return doc.root + os.path.relpath(
            os.path.join(self.other.out, target), self.out).replace(os.sep, "/")


EDITIONS = [
    Edition("en", "", "", "static/", "search-index.js"),
    Edition("ja", "ja", "ja", "../static/", "search-index.ja.js"),
]
EDITIONS[0].other, EDITIONS[1].other = EDITIONS[1], EDITIONS[0]


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

class Doc:
    def __init__(self, src, ed):
        self.src = src
        self.ed = ed
        rel = os.path.relpath(src, ed.content).replace(os.sep, "/")
        self.rel_out = rel[:-3] + ".html"
        self.label = ed.prefix + self.rel_out  # used in warnings
        self.depth = self.rel_out.count("/")
        self.meta, self.body = parse_front_matter(
            read(src), os.path.relpath(src, ROOT).replace(os.sep, "/"))
        self.id = self.meta.get("id") or rel[:-3]
        self.title = self.meta.get("title", self.id)
        self.kind = self.meta.get("kind", "page")
        self.layout = self.meta.get("layout", "default")

    @property
    def root(self):
        return "../" * self.depth


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def parse_front_matter(text, rel):
    meta = {}
    if not text.startswith("---\n"):
        warn("%s: no front matter" % rel)
        return meta, text
    end = text.find("\n---\n", 4)
    if end == -1:
        warn("%s: front matter not closed" % rel)
        return meta, text
    for line in text[4:end].split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            warn("%s: bad front matter line: %s" % (rel, line))
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, text[end + 5:]


def load_edition(ed):
    for dirpath, _dirs, files in os.walk(ed.content):
        for name in sorted(files):
            if name.endswith(".md"):
                ed.docs.append(Doc(os.path.join(dirpath, name), ed))
    ed.docs.sort(key=lambda d: d.rel_out)
    for d in ed.docs:
        if d.id in ed.index:
            warn("%s: duplicate id %s (%s, %s)" % (ed.lang, d.id, ed.index[d.id].label, d.label))
        ed.index[d.id] = d
        ed.by_path[d.rel_out] = d
    for name in os.listdir(ed.templates_dir):
        if name.endswith(".html"):
            ed.templates[name[:-5]] = read(os.path.join(ed.templates_dir, name))


# --------------------------------------------------------------------------
# Inline rendering
# --------------------------------------------------------------------------

AMP = re.compile(r"&(?!(#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);)")


def esc(s):
    return AMP.sub("&amp;", s).replace("<", "&lt;").replace(">", "&gt;")


class Ctx:
    def __init__(self, doc):
        self.doc = doc
        self.ed = doc.ed
        self.index = doc.ed.index
        self.root = doc.root


def render_link(inner, ctx):
    inner = inner.strip()
    if inner.startswith("x:"):
        body = inner[2:]
        if body.isdigit():
            body = "X" * int(body)
        return '<span class="x">%s</span>' % body
    if inner.startswith("denied:"):
        res, _, text = inner[7:].partition("|")
        return '<a href="%sdenied.html?r=%s">%s</a>' % (ctx.root, res.strip(), text or res)
    target, _, text = inner.partition("|")
    target = target.strip()
    text = text or target
    doc = ctx.index.get(target)
    if doc is None:
        warn("%s: broken link [[%s]]" % (ctx.doc.label, target))
        return '<a href="%s404.html">%s</a>' % (ctx.root, text)
    return '<a href="%s%s">%s</a>' % (ctx.root, doc.rel_out, text)


LINK = re.compile(r"\[\[(.+?)\]\]")
BOLD = re.compile(r"\*\*(.+?)\*\*")
ITALIC = re.compile(r"(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])")
CODE = re.compile(r"`([^`]+)`")


def inline(s, ctx, rich=True):
    s = esc(s)
    s = LINK.sub(lambda m: render_link(m.group(1), ctx), s)
    if rich:
        s = CODE.sub(r"<code>\1</code>", s)
        s = BOLD.sub(r"<b>\1</b>", s)
        s = ITALIC.sub(r"<i>\1</i>", s)
    return s


# --------------------------------------------------------------------------
# Block rendering
# --------------------------------------------------------------------------

def starts_block(s):
    return (s.startswith("```") or s.startswith(":::") or s.startswith("|")
            or s.startswith("- ") or s.startswith("#") or s.startswith("<")
            or s == "---")


def split_cells(row):
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    cells, buf, depth, i = [], "", 0, 0
    while i < len(row):
        if row.startswith("[[", i):
            depth += 1
            buf += "[["
            i += 2
            continue
        if row.startswith("]]", i) and depth:
            depth -= 1
            buf += "]]"
            i += 2
            continue
        if row[i] == "|" and not depth:
            cells.append(buf)
            buf = ""
        else:
            buf += row[i]
        i += 1
    cells.append(buf)
    return [c.strip() for c in cells]


CELL_OPT = re.compile(r"^\{([a-z]+)(?:=(\d+))?\}")


def render_cell(tag, text, ctx):
    classes, width = [], None
    while True:
        m = CELL_OPT.match(text)
        if not m:
            break
        if m.group(1) == "w":
            width = m.group(2)
        else:
            classes.append(m.group(1))
        text = text[m.end():].lstrip()
    attrs = ""
    if classes:
        attrs += ' class="%s"' % " ".join(classes)
    if width:
        attrs += ' width="%s"' % width
    return "<%s%s>%s</%s>" % (tag, attrs, inline(text, ctx), tag)


def render_table(lines, ctx):
    rows = [split_cells(r) for r in lines]
    header = None
    if len(rows) >= 2 and all(re.fullmatch(r":?-{3,}:?", c) for c in rows[1]):
        header, rows = rows[0], rows[2:]
    out = ['<div class="tbl"><table border="1" cellpadding="4" width="100%">']
    if header:
        out.append("<tr>" + "".join(render_cell("th", c, ctx) for c in header) + "</tr>")
    for r in rows:
        out.append("<tr>" + "".join(render_cell("td", c, ctx) for c in r) + "</tr>")
    out.append("</table></div>")
    return "\n".join(out)


def render_fence(info, lines, ctx):
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    cls = "doc tr" if info == "transcript" else "doc"
    body = "\n".join(inline(l, ctx, rich=False) for l in lines)
    return '<div class="%s">%s</div>' % (cls, body)


def render_para(lines, ctx):
    text = ""
    for i, line in enumerate(lines):
        if line.endswith("\\"):
            text += line[:-1].rstrip() + "\x02"
        else:
            text += line + (" " if i < len(lines) - 1 else "")
    cls = ""
    m = re.match(r"^\{([a-z ]+)\}\s*", text)
    if m:
        cls = ' class="%s"' % m.group(1)
        text = text[m.end():]
    return "<p%s>%s</p>" % (cls, inline(text, ctx).replace("\x02", "<br>\n"))


def render_raw(lines, ctx):
    s = "\n".join(lines).replace("{{root}}", ctx.root)
    return LINK.sub(lambda m: render_link(m.group(1), ctx), s)


def render_body(text, ctx):
    lines = text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if s.startswith("```"):
            info = s[3:].strip() or "doc"
            j = i + 1
            buf = []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                buf.append(lines[j].rstrip())
                j += 1
            out.append(render_fence(info, buf, ctx))
            i = j + 1
            continue
        if s.startswith(":::"):
            out.append(render_directive(s[3:].strip(), ctx))
            i += 1
            continue
        if s.startswith("<"):
            buf = []
            while i < len(lines) and lines[i].strip():
                buf.append(lines[i])
                i += 1
            out.append(render_raw(buf, ctx))
            continue
        if s.startswith("#"):
            m = re.match(r"(#+)\s+(.*)", s)
            tag = {1: "h2", 2: "h3"}.get(len(m.group(1)), "h4")
            out.append("<%s>%s</%s>" % (tag, inline(m.group(2), ctx), tag))
            i += 1
            continue
        if s == "---":
            out.append("<hr>")
            i += 1
            continue
        if s.startswith("|"):
            buf = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                buf.append(lines[i].strip())
                i += 1
            out.append(render_table(buf, ctx))
            continue
        if s.startswith("- "):
            items = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                item = lines[i].strip()[2:]
                i += 1
                while (i < len(lines) and lines[i].startswith("  ") and lines[i].strip()
                       and not lines[i].strip().startswith("- ")):
                    item += " " + lines[i].strip()
                    i += 1
                items.append(item)
            out.append("<ul>" + "".join("<li>%s</li>" % inline(x, ctx) for x in items) + "</ul>")
            continue
        buf = []
        while i < len(lines) and lines[i].strip() and not starts_block(lines[i].strip()):
            buf.append(lines[i].strip())
            i += 1
        out.append(render_para(buf, ctx))
    return "\n".join(out)


# --------------------------------------------------------------------------
# Directives (::: name args)
# --------------------------------------------------------------------------

def wav_info(path):
    """Audio files live in static/audio/ and are shared by every edition."""
    try:
        with wave.open(path, "rb") as w:
            frames, rate = w.getnframes(), w.getframerate()
            bits, ch = w.getsampwidth() * 8, w.getnchannels()
        secs = frames / float(rate)
        return {
            "dur": "%d:%02d" % (int(secs) // 60, int(secs) % 60),
            "khz": round(rate / 1000.0),
            "bits": bits,
            "mono": ch == 1,
            "size": "%d KB" % round(os.path.getsize(path) / 1024.0),
        }
    except (OSError, wave.Error, EOFError):
        return None


def wav_fmt(info, s):
    return s["fmt"] % (info["khz"], info["bits"], s["mono"] if info["mono"] else s["stereo"])


def collect_audio(ed):
    for d in ed.docs:
        for line in d.body.split("\n"):
            s = line.strip()
            if s.startswith("::: audio "):
                f, label, note = (s[len("::: audio "):].split("|") + ["", ""])[:3]
                ed.audio_refs.append((d, f.strip(), label.strip(), note.strip()))


def render_audio(args, ctx):
    s = ctx.ed.s
    f, label, note = (args.split("|") + ["", ""])[:3]
    f, label, note = f.strip(), label.strip(), note.strip()
    src = os.path.join(STATIC, "audio", f)
    info = wav_info(src)
    url = "%s%saudio/%s" % (ctx.root, ctx.ed.static, f)
    if info is None:
        warn("%s: audio file missing: %s" % (ctx.doc.label, f))
        return ('<div class="audbox"><b>%s: %s</b> &nbsp; <span class="m small">%s</span><br>'
                '<span class="m small">%s</span></div>'
                % (s["audio"], esc(label), esc(note), s["audio_missing"]))
    meta = " &middot; ".join(x for x in [esc(note), wav_fmt(info, s), info["dur"], info["size"]] if x)
    return ('<div class="audbox"><b>%s: %s</b> &nbsp; <span class="m small">%s</span><br>'
            '<span class="aud" data-src="%s"><button type="button" class="ap">%s</button> '
            '<button type="button" class="as">%s</button> '
            '<span class="at m">00:00 / %s</span></span> &nbsp; '
            '<span class="small">[ <a href="%s">%s</a> ]</span></div>'
            % (s["audio"], esc(label), meta, url, s["play"], s["stop"],
               info["dur"].rjust(5, "0"), url, s["download"]))


def render_records(ctx):
    s = ctx.ed.s
    out = []
    docs = [d for d in ctx.index.values() if d.kind != "page"]
    for kind in RECORD_KINDS:
        group = sorted((d for d in docs if d.kind == kind),
                       key=lambda d: (d.meta.get("date", ""), d.id))
        if not group:
            continue
        out.append("<h3>%s</h3>" % s["record_kinds"][kind])
        out.append('<div class="tbl"><table border="1" cellpadding="4" width="100%">')
        out.append('<tr><th width="120">%s</th><th width="96">%s</th><th>%s</th></tr>' % s["records_head"])
        for d in group:
            out.append('<tr><td class="m"><a href="%s%s">%s</a></td><td class="m">%s</td><td>%s</td></tr>'
                       % (ctx.root, d.rel_out, esc(d.id), esc(d.meta.get("date", "--")),
                          inline(d.meta.get("summary", d.title), ctx)))
        out.append("</table></div>")
    return "\n".join(out)


def render_audio_list(ctx):
    s = ctx.ed.s
    out = ['<div class="tbl"><table border="1" cellpadding="4" width="100%">',
           "<tr><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr>" % s["audio_list_head"]]
    for d, f, label, note in ctx.ed.audio_refs:
        info = wav_info(os.path.join(STATIC, "audio", f))
        out.append('<tr><td class="m">%s</td><td class="m">%s</td><td class="m">%s</td>'
                   '<td><a href="%s%s">%s</a></td></tr>'
                   % (esc(label), wav_fmt(info, s) if info else "--", info["dur"] if info else "--",
                      ctx.root, d.rel_out, esc(d.id)))
    out.append("</table></div>")
    return "\n".join(out)


def render_directive(s, ctx):
    name, _, args = s.partition(" ")
    if name == "audio":
        return render_audio(args, ctx)
    if name == "records":
        return render_records(ctx)
    if name == "audio-list":
        return render_audio_list(ctx)
    warn("%s: unknown directive ::: %s" % (ctx.doc.label, name))
    return ""


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

def crumb_html(doc):
    parent = doc.meta.get("parent")
    if not parent:
        return ""
    p = doc.ed.index.get(parent)
    if p is None:
        warn("%s: unknown parent %s" % (doc.label, parent))
        return ""
    label = p.meta.get("short", p.title)
    return '<div class="crumb"><a href="%s%s">%s</a> &gt; %s</div>' % (
        doc.root, p.rel_out, esc(label), esc(doc.id))


def render_page(doc):
    ed = doc.ed
    ctx = Ctx(doc)
    body = render_body(doc.body, ctx)
    tpl = ed.templates.get(doc.layout)
    if tpl is None:
        warn("%s: unknown layout %s" % (doc.label, doc.layout))
        tpl = ed.templates["default"]
    title_html = "" if doc.meta.get("notitle") == "yes" else "<h2>%s</h2>" % esc(doc.title)
    repl = {
        "{{root}}": doc.root,
        "{{static}}": doc.root + ed.static,
        "{{alt}}": ed.alt_href(doc),
        "{{search_index}}": ed.search_index,
        "{{id}}": esc(doc.id),
        "{{title}}": esc(doc.title),
        "{{title_html}}": title_html,
        "{{crumb}}": crumb_html(doc),
        "{{content}}": body,
        "{{doc}}": esc(doc.meta.get("doc", "PIS-000")),
        "{{modified}}": esc(doc.meta.get("modified", "--")),
        "{{classification}}": esc(doc.meta.get("classification", ed.s["classification"])),
        "{{track}}": "no" if doc.meta.get("track") == "no" else "yes",
    }
    out = tpl
    for k, v in repl.items():
        out = out.replace(k, v)
    return out


def search_index(ed):
    items = []
    for d in ed.docs:
        if d.meta.get("search") == "no":
            continue
        items.append({
            "i": d.id, "t": d.title, "u": d.rel_out,
            "s": d.meta.get("summary", ""), "k": d.meta.get("keywords", ""),
        })
    return "window.PIS_INDEX = " + json.dumps(items, ensure_ascii=False, indent=0) + ";\n"


def main():
    strict = "--strict" in sys.argv
    for ed in EDITIONS:
        load_edition(ed)
        collect_audio(ed)

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    for ed in EDITIONS:
        for d in ed.docs:
            path = os.path.join(ed.out, d.rel_out)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(render_page(d))
    shutil.copytree(STATIC, os.path.join(OUT, "static"))
    for ed in EDITIONS:
        with open(os.path.join(OUT, "static", ed.search_index), "w", encoding="utf-8") as f:
            f.write(search_index(ed))
    with open(os.path.join(OUT, ".nojekyll"), "w") as f:
        f.write("")

    for w in warnings:
        print("WARNING: " + w)
    for ed in EDITIONS:
        missing = [d.label for d in ed.docs if d.rel_out not in ed.other.by_path]
        if missing:
            print("NOTE: not in the %s edition yet (linked to its index): %s"
                  % (ed.other.lang, ", ".join(missing)))
    print("Built %s into %s" % (", ".join("%d %s documents" % (len(ed.docs), ed.lang) for ed in EDITIONS),
                                os.path.relpath(OUT, ROOT)))
    if strict and warnings:
        sys.exit(1)


if __name__ == "__main__":
    main()
