#!/usr/bin/env python3
"""Multi-source SFX search & download (stdlib only).

Ranking follows the workflow this skill documents: libraries that carry human
feedback (downloads, ratings, descriptions) come first, but Kenney wins for UI
sounds because its packs are purpose-built for interface clicks/switches.

  sfx.py search    "<query>"   aggregate every source, ranked
  sfx.py freesound "<query>"   ↓downloads ★rating(votes) description
  sfx.py mixkit    "<query>"   title + duration only (no human feedback)
  sfx.py kenney    "<query>"   local CC0 pack index (first run downloads ~1 MB)
  sfx.py get <dir> fs:<id> mk:<id> kn:<path>
"""
import argparse, html, io, json, re, shutil, subprocess, sys, time
import urllib.parse, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
CACHE = Path.home() / ".cache" / "sfx-sources"
INDEX = CACHE / "index.json"          # search results, so `get` knows title + download url
KENNEY = CACHE / "kenney"            # unpacked CC0 packs

FS_LICENSE = {"cc0": '"Creative Commons 0"', "by": '("Attribution" OR "Creative Commons 0")', "any": None}
FS_LIC_SHORT = {"Creative Commons 0": "CC0", "Attribution": "BY",
                "Attribution NonCommercial": "BY-NC", "Sampling+": "Sampling+"}
FS_SORT = {"downloads": "Downloads (most first)", "rating": "Rating (highest first)",
           "relevance": "Automatic by relevance", "short": "Duration (shortest first)"}

# Kenney packs worth indexing for video work. id = hex("assets/<slug>"), as the site's
# own download button carries it; the slug is kept next to it for readability.
KENNEY_PACKS = [("ui-audio", "UI audio"), ("interface-sounds", "Interface sounds")]

# Cues where Kenney outranks a human-feedback library: purpose-built interface audio.
UI_HINTS = {"click", "clicks", "switch", "button", "pop", "popup", "toggle", "ui", "interface",
            "rollover", "hover", "select", "selection", "menu", "tap", "tick", "beep", "cursor",
            "notification", "confirm", "error", "success", "check", "tick", "slide", "whoosh"}


def fetch(url, timeout=60, tries=3):
    for n in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except Exception as e:
            if n == tries - 1:
                raise e if isinstance(e, OSError) else OSError(repr(e))
            time.sleep(1 + n)


def load_index():
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_index(rows):
    CACHE.mkdir(parents=True, exist_ok=True)
    idx = load_index()
    idx.update({r["key"]: r for r in rows})
    INDEX.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")


def _fmt(rows, a, lic=False):
    save_index(rows)
    for r in rows:
        cols = [r["key"], r["title"], r["dur"]]
        if "stats" in r:
            cols.append(r["stats"])
        if lic:
            cols.append(r["license"])
        if r.get("desc"):
            cols.append(r["desc"])
        if a.urls:
            cols.append(r["preview"])
        print("\t".join(cols))
    if not rows:
        print("(none)")


# ---------------------------------------------------------------- Freesound

def freesound(a):
    """Scrape Freesound's search HTML. Their API needs a token (401 without one)."""
    q = {"q": a.query, "s": FS_SORT[a.sort]}
    if FS_LICENSE[a.license]:
        q["f"] = "license:" + FS_LICENSE[a.license]
    pages = range(a.page, a.page + a.pages)
    with ThreadPoolExecutor(len(pages)) as ex:
        htmls = list(ex.map(lambda n: fetch(
            "https://freesound.org/search/?" + urllib.parse.urlencode({**q, "page": n})).decode(), pages))
    rows = []
    for blk in (b for h in htmls for b in h.split('class="bw-search__result"')[1:]):
        g = lambda k: (re.search(rf'data-{k}="([^"]*)"', blk) or [None, ""])[1]
        lic = re.search(r'title="License: ([^"]+)"', blk)
        rt = re.search(r'aria-label="Average rating of ([\d.]+)"', blk)
        rn = re.search(r'bw-rating__count[^>]*>\((\d+)\)', blk)
        desc = re.search(r'<div class="max-h-60px[^"]*"\s*>\s*(.*?)\s*</div>', blk, re.S)
        sid, user, dl = g("sound-id"), g("username"), int(g("num-downloads") or 0)
        if not sid:
            continue
        rows.append({"key": f"fs:{sid}", "title": html.unescape(g("title")),
                     "dur": f"{float(g('duration') or 0):.1f}s", "author": user,
                     "license": FS_LIC_SHORT.get(lic.group(1), lic.group(1)) if lic else "?",
                     "preview": g("mp3").replace("-lq.mp3", "-hq.mp3"),
                     "url": g("mp3").replace("-lq.mp3", "-hq.mp3"), "downloads": dl,
                     "stats": f"↓{dl} ★{rt[1]}({rn[1]})" if rt and rn else f"↓{dl} ★-",
                     # the uploader's own words (mic, source, processing) are the closest thing to hearing it
                     "desc": html.unescape(re.sub(r"<[^>]+>|\s+", " ", desc[1])).strip()[:90] if desc else "",
                     "source": "freesound"})
    if a.sort == "relevance":
        rows.sort(key=lambda r: -r["downloads"])
    return rows


# ---------------------------------------------------------------- Mixkit

MK_CARD = 'class="item-grid-card item-grid-card--show-meta"'


def _mixkit_parse(h, limit):
    rows = []
    for blk in h.split(MK_CARD)[1:]:
        sid = re.search(r'data-audio-player-item-id-value="(\d+)"', blk)
        mp3 = re.search(r'data-audio-player-preview-url-value="([^"]+)"', blk)
        title = re.search(r'class="item-grid-card__title">\s*(.*?)\s*</h2>', blk, re.S)
        dur = re.search(r'data-test-id="duration">\s*([\d:]+)\s*<', blk)
        if not (sid and mp3 and title):
            continue
        rows.append({"key": f"mk:{sid.group(1)}",
                     "title": html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip(),
                     "dur": (dur.group(1) + "s") if dur else "?", "author": "Mixkit",
                     "license": "Mixkit Free", "preview": mp3.group(1), "url": mp3.group(1),
                     "desc": "", "source": "mixkit"})
        if len(rows) >= limit:
            break
    return rows


def mixkit(a):
    """Scrape mixkit.co. Cards carry title + duration only — no ratings, no download counts.

    Mixkit's ?q= parameter returns an unrelated default list, so the keyword has to go in
    the path (/free-sound-effects/<keyword>/). Multi-word queries are reduced to their
    first term; on a path miss, fall back to filtering the default grid by title.
    """
    kw = re.sub(r"[^a-z0-9]+", "-", a.query.lower()).strip("-").split("-")[0]
    if kw:
        try:
            rows = _mixkit_parse(fetch(f"https://mixkit.co/free-sound-effects/{kw}/").decode("utf-8", "replace"),
                                 a.n * 3)
            if rows:
                return rows
        except Exception:
            pass
    h = fetch("https://mixkit.co/free-sound-effects/").decode("utf-8", "replace")
    terms = [t for t in re.split(r"[^a-z0-9]+", a.query.lower()) if t]
    return [r for r in _mixkit_parse(h, 400) if all(t in r["title"].lower() for t in terms)]


# ---------------------------------------------------------------- Kenney

def _kenney_zip(slug):
    """Kenney hands out a freshly signed URL per request; the id is the hex of assets/<slug>.
    A Referer is mandatory — without it the endpoint answers 403."""
    did = ("assets/" + slug).encode().hex()
    hdr = {**UA, "Referer": f"https://kenney.nl/assets/{slug}"}
    try:
        req = urllib.request.Request(f"https://kenney.nl/download-link/{did}", headers=hdr)
        with urllib.request.urlopen(req, timeout=45) as r:
            j = json.loads(r.read())
    except Exception:
        return None
    return j.get("url")


def ensure_kenney(verbose=True):
    """Download + unpack the CC0 packs once. ~1 MB total, cached under ~/.cache."""
    KENNEY.mkdir(parents=True, exist_ok=True)
    for slug, label in KENNEY_PACKS:
        dest = KENNEY / slug
        if dest.exists() and any(dest.rglob("*.*")):
            continue
        if verbose:
            print(f"# fetching Kenney pack '{label}' (CC0)…", file=sys.stderr)
        u = _kenney_zip(slug)
        if not u:
            if verbose:
                print(f"# ! could not resolve Kenney pack {slug}", file=sys.stderr)
            continue
        try:
            req = urllib.request.Request(u, headers={**UA, "Referer": f"https://kenney.nl/assets/{slug}"})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = r.read()
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                z.extractall(dest)
        except Exception as e:
            if verbose:
                print(f"# ! Kenney pack {slug} failed: {e!r}", file=sys.stderr)
    return KENNEY


def _kenney_files():
    exts = {".ogg", ".wav", ".mp3", ".m4a", ".flac"}
    out = []
    if KENNEY.exists():
        for p in KENNEY.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                out.append(p)
    return out


def kenney(a):
    ensure_kenney()
    terms = [t for t in re.split(r"[^a-z0-9]+", a.query.lower()) if t]
    rows = []
    for p in _kenney_files():
        stem = p.stem.lower()
        score = sum(2 if t in stem else 0 for t in terms)
        if terms and not score:
            continue
        rows.append({"key": f"kn:{p.relative_to(KENNEY).as_posix()}", "title": p.stem,
                     "dur": "?", "author": "Kenney", "license": "CC0", "preview": "",
                     "url": "", "path": str(p), "desc": f"{p.suffix.lstrip('.')} · {p.parent.name}",
                     "score": score, "source": "kenney"})
    rows.sort(key=lambda r: (-r["score"], r["title"]))
    return rows


# ---------------------------------------------------------------- aggregate

def _is_ui(query):
    return bool(set(re.split(r"[^a-z0-9]+", query.lower())) & UI_HINTS)


def search(a):
    """Run every source, then rank the way the documented workflow says."""
    order = ["kenney", "freesound", "mixkit"] if _is_ui(a.query) else ["freesound", "mixkit", "kenney"]
    a_sort = argparse.Namespace(**{**vars(a), "sort": "relevance", "pages": 2, "page": 1,
                                   "license": a.license, "n": a.n, "urls": a.urls})
    buckets = {}
    for name in order:
        try:
            buckets[name] = (kenney if name == "kenney" else freesound if name == "freesound" else mixkit)(a_sort)[: a.n]
        except Exception as e:
            print(f"# {name}: {e!r}", file=sys.stderr)
            buckets[name] = []

    print(f"# query={a.query!r}  {'UI cue → Kenney first' if _is_ui(a.query) else 'not a UI cue → human-feedback first'}")
    print(f"# order: {' > '.join(order)}")
    rows = []
    for name in order:
        b = buckets.get(name) or []
        if not b:
            continue
        print(f"\n## {name} ({len(b)})")
        _fmt(b, a, lic=(name == "freesound" and a.license != "cc0"))
        rows += b
    if not rows:
        print("(none)")


# ---------------------------------------------------------------- download

def _to_mp3(src, dst):
    """Kenney ships .ogg, which most NLEs refuse. Convert when ffmpeg exists."""
    if src.suffix.lower() == ".mp3":
        shutil.copy2(src, dst)
        return True
    ff = shutil.which("ffmpeg")
    if not ff:
        return False
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src),
                        "-codec:a", "libmp3lame", "-qscale:a", "2", str(dst)],
                       capture_output=True)
    return r.returncode == 0 and dst.exists()


def get(a):
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    idx = load_index()

    def one(key):
        src_tag, sep, ref = key.partition(":")
        if src_tag == "kn":
            p = KENNEY / ref
            if not p.exists():
                return key, None, "unknown key — run `kenney` first"
            dst = out / f"kn_{re.sub(r'[^\w]+', '-', p.stem)}{'.mp3' if shutil.which('ffmpeg') else p.suffix}"
            if not dst.exists() and not _to_mp3(p, dst):
                dst = out / p.name
                if not dst.exists():
                    shutil.copy2(p, dst)
            return key, dst, None if dst.suffix == ".mp3" else "raw ogg (ffmpeg not found)"
        if not sep or src_tag not in ("fs", "mk"):
            return key, None, "unsupported key — use fs:/mk:/kn:"
        r = idx.get(key)
        if not r:
            return key, None, "unknown key — search first"
        slug = re.sub(r"[^\w]+", "-", r["title"]).strip("-")[:40]
        dst = out / f"{src_tag}_{ref}{'_' + slug if slug else ''}{Path(urllib.parse.urlparse(r['url']).path).suffix}"
        if not dst.exists():
            tmp = dst.with_suffix(dst.suffix + ".part")
            tmp.write_bytes(fetch(r["url"], timeout=300))
            tmp.rename(dst)
        lic = r.get("license", "CC0")
        return key, dst, f"credit {r.get('author', '?')}" if lic not in ("CC0", "Mixkit Free") else None

    def safe(key):
        try:
            return one(key)
        except Exception as e:  # one bad file shouldn't sink the batch
            return key, None, repr(e)

    # Freesound caps ~80 KB/s per connection, so parallelism is the only speed lever.
    with ThreadPoolExecutor(6) as ex:
        for key, dst, note in ex.map(safe, a.keys):
            print(f"FAIL {key}: {note}" if not dst else f"{dst.name}  [{note}]" if note else dst.name)


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("query")
        p.add_argument("-n", type=int, default=8)
        p.add_argument("--urls", action="store_true")

    s = sp.add_parser("search"); common(s)
    s.add_argument("--license", choices=FS_LICENSE, default="any"); s.set_defaults(fn=search)

    f = sp.add_parser("freesound"); common(f)
    f.add_argument("--license", choices=FS_LICENSE, default="any")
    f.add_argument("--sort", choices=FS_SORT, default="relevance")
    f.add_argument("-p", "--page", type=int, default=1)
    f.add_argument("--pages", type=int, default=3, help="relevance pages (15 each) to rank by downloads")
    f.set_defaults(fn=lambda a: _fmt(freesound(a), a, lic=a.license != "cc0"))

    m = sp.add_parser("mixkit"); common(m); m.set_defaults(fn=lambda a: _fmt(mixkit(a), a))
    k = sp.add_parser("kenney"); common(k); k.set_defaults(fn=lambda a: _fmt(kenney(a), a))

    g = sp.add_parser("get"); g.add_argument("out_dir"); g.add_argument("keys", nargs="+"); g.set_defaults(fn=get)

    a = ap.parse_args()
    try:
        a.fn(a)
    except OSError as e:
        sys.exit(f"network error: {getattr(e, 'reason', e)}")


if __name__ == "__main__":
    main()
