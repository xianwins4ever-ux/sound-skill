#!/usr/bin/env python3
"""Multi-source SFX search & download (stdlib only, plus curl_cffi for Pixabay).

Ranking follows the workflow this skill documents: libraries that carry human
feedback (likes, downloads, ratings, descriptions) come first, but Kenney wins
for UI sounds because its packs are purpose-built for interface clicks/switches.

  sfx.py search    "<query>"   aggregate every source, ranked
  sfx.py pixabay   "<query>"   ♥likes ↓downloads (Cloudflare → curl_cffi venv)
  sfx.py freesound "<query>"   ↓downloads ★rating(votes) description
  sfx.py mixkit    "<query>"   title + duration only (no human feedback)
  sfx.py kenney    "<query>"   local CC0 pack index (first run downloads ~1 MB)
  sfx.py get <dir> px:<id> fs:<id> mk:<id> kn:<path>
"""
import argparse, html, io, json, os, platform, re, shutil, subprocess, sys, threading, time
import urllib.error, urllib.parse, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}
CACHE = Path.home() / ".cache" / "sfx-sources"
INDEX = CACHE / "index.json"          # search results, so `get` knows title + download url
KENNEY = CACHE / "kenney"            # unpacked CC0 packs
VENV = CACHE / "venv"                # curl_cffi venv (Pixabay sits behind Cloudflare)

FS_LICENSE = {"cc0": '"Creative Commons 0"', "by": '("Attribution" OR "Creative Commons 0")', "any": None}
FS_LIC_SHORT = {"Creative Commons 0": "CC0", "Attribution": "BY",
                "Attribution NonCommercial": "BY-NC", "Sampling+": "Sampling+"}
FS_SORT = {"downloads": "Downloads (most first)", "rating": "Rating (highest first)",
           "relevance": "Automatic by relevance", "short": "Duration (shortest first)"}

# Kenney packs worth indexing for video work. id = hex("assets/<slug>"), as the site's
# own download button carries it; the slug is kept next to it for readability.
KENNEY_PACKS = [("ui-audio", "UI audio"), ("interface-sounds", "Interface sounds")]

# Cues where Kenney outranks a human-feedback library: purpose-built interface audio.
# Deliberately narrow — the two bundled packs are clicks/toggles/blips only, so a
# transition cue like "whoosh" or "slide" must NOT route here (it would find nothing).
UI_HINTS = {"click", "clicks", "switch", "switches", "button", "buttons", "pop", "popup",
            "toggle", "ui", "interface", "rollover", "hover", "select", "selection", "menu",
            "tap", "tick", "beep", "cursor", "notification", "alert", "confirm", "confirmation",
            "error", "success", "check", "back", "close", "drop", "bong", "glitch", "blip"}


def _venv_python(venv):
    return venv / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")


def _ensure_cffi(verbose=True):
    """Make `curl_cffi` importable, building a private venv on first use.

    Pixabay answers plain urllib with a Cloudflare 403 ("Just a moment…"), so its
    requests have to look like a real browser. curl_cffi does that by impersonating
    Chrome's TLS fingerprint.

    Two portability traps this avoids, both of which break the upstream script on
    Windows: the venv interpreter is Scripts/python.exe there, not bin/python; and
    re-exec'ing the script under the venv (os.execv) loses the caller's cwd and
    quoting. Instead the venv's site-packages is appended to sys.path and imported
    in-process — same interpreter version, so the compiled extension loads fine.
    """
    try:
        import curl_cffi  # noqa: F401
        return True
    except ImportError:
        pass

    # Two attempts: the second rebuilds the venv from scratch. The old code only built
    # when the interpreter was missing, so a venv with a broken site-packages returned
    # False forever and Pixabay stayed dead with no message.
    for attempt in (0, 1):
        if attempt:
            if verbose:
                print("# curl_cffi import still failing — rebuilding the venv", file=sys.stderr)
            shutil.rmtree(VENV, ignore_errors=True)
        py = _venv_python(VENV)
        if not py.exists():
            if verbose:
                print("# setting up curl_cffi venv for Pixabay (one-time, ~10 s)…", file=sys.stderr)
            try:
                subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True,
                               capture_output=True)
                subprocess.run([str(py), "-m", "pip", "-q", "install", "curl_cffi"], check=True,
                               capture_output=True)
            except Exception as e:
                if verbose:
                    print(f"# ! curl_cffi setup failed: {e!r}", file=sys.stderr)
                return False
        for sp in list(VENV.glob("Lib/site-packages")) + list(VENV.glob("lib/python*/site-packages")):
            if str(sp) not in sys.path:
                sys.path.insert(0, str(sp))
        try:
            import curl_cffi  # noqa: F401
            return True
        except ImportError:
            continue
    if verbose:
        print("# ! curl_cffi could not be imported — Pixabay unavailable", file=sys.stderr)
    return False


def fetch(url, timeout=60, tries=3):
    for n in range(tries):
        try:
            if "pixabay.com" in url:      # Cloudflare 403s plain urllib; cdn.* is routed too
                if not _ensure_cffi():
                    raise OSError("Pixabay needs curl_cffi, which could not be installed")
                from curl_cffi import requests as cr
                r = cr.get(url, impersonate="chrome", timeout=timeout,
                           headers={"Referer": "https://pixabay.com/"})
                if r.status_code == 429:
                    _rate_limited(url, n, tries)
                    continue
                if r.status_code != 200:
                    raise OSError(f"HTTP {r.status_code} {url}")
                return r.content
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            # Every catalog rate-limits, not just Pixabay — Freesound answers 429 too when
            # several searches run at once. A 1s/2s backoff just burns the retries.
            if e.code == 429:
                _rate_limited(url, n, tries)
                continue
            if n == tries - 1:
                raise OSError(f"HTTP {e.code} {url}") from None
            time.sleep(1 + n)
        except Exception as e:
            if n == tries - 1:
                raise e if isinstance(e, OSError) else OSError(repr(e))
            time.sleep(1 + n)   # Cloudflare 403s are sporadic; a short pause usually clears them


def _rate_limited(url, n, tries):
    host = urllib.parse.urlparse(url).netloc
    if n == tries - 1:
        raise OSError(f"HTTP 429 — {host} is rate-limiting this machine; wait a minute "
                      f"and retry, or use -n fewer / --pages 1")
    wait = 8 * (n + 1)
    print(f"# {host} rate-limited (429) — waiting {wait}s", file=sys.stderr)
    time.sleep(wait)


def load_index():
    """Read the search cache.

    A corrupt file is moved aside rather than reported as empty. The previous version
    returned {} here, and the next save_index() then wrote that {} plus one new row back
    over the file — silently destroying every cached key (measured: 599 keys → 1).
    """
    try:
        return json.loads(INDEX.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        keep = INDEX.parent / f"{INDEX.name}.corrupt-{int(time.time())}"
        try:
            INDEX.replace(keep)
            print(f"# index.json was unreadable ({e.__class__.__name__}) — kept it as "
                  f"{keep.name}, starting a fresh cache", file=sys.stderr)
        except OSError:
            pass
        return {}


def save_index(rows):
    """Merge rows into the cache and write it atomically.

    Closes two failure modes: write_text() truncates in place, so a crash mid-write
    leaves an unreadable cache; and writing to the live path lets two concurrent
    searches interleave. Empty input never touches the file — `kenney --packs` used to
    call save_index([]) and rewrite the cache for no reason.
    """
    rows = [r for r in rows if r.get("key")]
    if not rows:
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    idx = load_index()
    idx.update({r["key"]: r for r in rows})
    tmp = INDEX.parent / f"{INDEX.name}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, INDEX)      # atomic on both Windows and POSIX


def _parse_dur(s):
    """'1s' / '0:01s' / '1:02:03s' / '?' → seconds (float) or None."""
    if not s or s == "?":
        return None
    s = str(s).strip().rstrip("s")
    try:
        if ":" in s:
            return sum(float(x) * 60 ** i for i, x in enumerate(reversed(s.split(":"))))
        return float(s)
    except ValueError:
        return None


def _find_tool(name):
    """Locate ffmpeg/ffprobe. PATH first, then the usual install spots.

    Both are looked up the same way on purpose: ffprobe used to have fallback paths
    while ffmpeg did not, so a machine with FFmpeg installed but not on PATH could
    measure a clip's duration and still fail to convert it.
    """
    exe = shutil.which(name)
    if exe:
        return exe
    sub = f"{name}.exe" if platform.system() == "Windows" else name
    for d in (Path("C:/Program Files/FFmpeg/bin"),
              Path("D:/AgentHub/_tools/hyperframes-tools/ffmpeg"),
              Path("/usr/bin"), Path("/usr/local/bin"), Path("/opt/homebrew/bin")):
        c = d / sub
        if c.exists():
            return str(c)
    return None


def _find_ffprobe():
    return _find_tool("ffprobe")


def _ffprobe_dur(p):
    """Measured duration in seconds, or None when ffprobe is unavailable.

    The catalog duration is useless for short one-shots: Pixabay rounds to whole seconds
    (a 0.575 s whoosh prints as "1s"), Mixkit rounds up ("0:01s" is really 0.452 s), and
    Kenney has none at all. Measuring the downloaded file is the only trustworthy number.
    """
    exe = _find_ffprobe()
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(p)],
                           capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip())
    except Exception:
        return None


def _peak_db(p):
    """Peak level in dBFS, or None. Positive means the file is already clipping.

    Measured on real Pixabay hits: one popular whoosh peaks at +1.5 dBFS — it will
    distort the moment it is placed in a mix, and nothing in the listing says so.
    """
    exe = _find_tool("ffmpeg")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "-hide_banner", "-i", str(p), "-af",
                            "astats=metadata=1:reset=0", "-f", "null", "-"],
                           capture_output=True, text=True, timeout=120)
        m = re.search(r"Peak level dB:\s*(-?[\d.]+|-?inf)", r.stderr)
        if not m or "inf" in m.group(1):
            return None
        return float(m.group(1))
    except Exception:
        return None


def _filter_dur(rows, a):
    """Apply --min-dur / --max-dur.

    Two deliberate concessions, both learned from testing:

    * Rows with an unknown duration are kept. Dropping them would hide Kenney entirely.
    * The listed duration is rounded, and always *up* on Pixabay/Mixkit (a 0.479 s pop
      prints as "1s", a 0.452 s page turn as "0:01s"). A hard `--max-dur 0.8` therefore
      rejected the very 0.48 s clips the flag exists to find. So the upper bound gets
      one second of slack; `get` prints the real measured length for the final call.
    """
    lo, hi = getattr(a, "min_dur", None), getattr(a, "max_dur", None)
    if lo is None and hi is None:
        return rows
    out = []
    for r in rows:
        d = _parse_dur(r.get("dur"))
        if d is not None:
            if lo is not None and d < lo:
                continue
            if hi is not None and d > hi + 1.0:
                continue
        out.append(r)
    return out


def _fmt(rows, a, lic=False):
    """Print rows, return how many survived the duration filter.

    Everything is cached before filtering — a `--max-dur` run must not evict the long
    clips from the index, or a later `get` on one of them fails as an unknown key.
    """
    save_index(rows)
    total = len(rows)
    rows = _filter_dur(rows, a)
    for r in rows:
        cols = [r["key"], r["title"], r["dur"]]
        if "stats" in r:
            cols.append(r["stats"])
        if lic:
            cols.append(r["license"])
        if r.get("desc"):
            cols.append(r["desc"])
        if a.urls and r.get("preview"):     # Kenney has no preview url — do not emit a blank column
            cols.append(r["preview"])
        print("\t".join(cols))
    if not rows and not getattr(a, "packs", False):
        if total:
            print(f"(none within --min-dur/--max-dur; {total} result(s) were filtered out)")
        else:
            print("(none)")
    return len(rows)


# ---------------------------------------------------------------- Freesound

def freesound(a):
    """Scrape Freesound's search HTML. Their API needs a token (401 without one)."""
    q = {"q": a.query, "s": FS_SORT[a.sort]}
    if FS_LICENSE[a.license]:
        q["f"] = "license:" + FS_LICENSE[a.license]
    pages = range(a.page, a.page + max(1, a.pages))
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
    if not rows:
        if all(ord(c) < 128 for c in a.query):
            print("# freesound: parsed 0 results — if the site loads fine in a browser, its "
                  "markup changed and the selectors need updating", file=sys.stderr)
    return rows[: a.n]


# ---------------------------------------------------------------- Pixabay

def k_num(t):  # "2.4K" -> 2400
    m = re.match(r"([\d.]+)\s*([KM]?)", t or "")
    return int(float(m[1]) * {"": 1, "K": 1e3, "M": 1e6}[m[2]]) if m else 0


def pixabay(a):
    """Scrape pixabay.com/sound-effects. Largest free catalog, no attribution required.

    Pixabay cannot sort by likes server-side, so pull several relevance pages, rank the
    cards by their rounded like counter, then open only the top n detail pages — exact
    likes/downloads, duration and the real mp3 URL live in each page's JSON-LD.
    """
    q = urllib.parse.quote(a.query.strip())
    pages = range(a.page, a.page + max(1, a.pages))
    with ThreadPoolExecutor(len(pages)) as ex:
        htmls = list(ex.map(lambda n: fetch(
            f"https://pixabay.com/sound-effects/search/{q}/" + (f"?pagi={n}" if n > 1 else "")
        ).decode("utf-8", "replace"), pages))
    seen, cards = set(), []
    for h in htmls:
        for blk in h.split('<div class="nameAndTitle')[1:]:
            t = re.search(r'<a href="(/sound-effects/[^"]*?-(\d+)/)" class="title[^"]*">(.*?)</a>'
                          r'<a href="/users/[^"]*" class="name[^"]*">(.*?)</a>', blk)
            if t and t[2] not in seen:
                seen.add(t[2])
                cnt = re.search(r'counter="([^"]*)"', blk)
                cards.append((t[1], t[2], html.unescape(t[3]), html.unescape(t[4]),
                              k_num(cnt[1] if cnt else "")))
    cards.sort(key=lambda c: -c[4])

    def detail(c):
        path, sid, title, user, likes = c
        dl, dur, url, note = 0, "?", "", ""
        try:
            # tries=1: under a 429 the default backoff would stall 8-24 s per card for
            # eight cards. One quick attempt, then keep the card without its mp3.
            d = fetch("https://pixabay.com" + path, tries=1).decode("utf-8", "replace")
            j = next(x for x in map(json.loads, re.findall(
                r'<script type="application/ld\+json">(.*?)</script>', d, re.S))
                if x.get("@type") == "AudioObject")
            st = {i["interactionType"].rsplit("/", 1)[-1]: i["userInteractionCount"]
                  for i in j.get("interactionStatistic", [])}
            likes, dl = st.get("LikeAction", likes), st.get("DownloadAction", 0)
            m = re.match(r"PT(?:(\d+)M)?(\d+)S", j.get("duration", "") or "")
            dur = f"{int(m[1] or 0) * 60 + int(m[2])}s" if m else "?"
            url = j["contentUrl"]
        except Exception as e:
            note = "detail unavailable — " + str(e)[:60]
        return {"key": f"px:{sid}", "title": title, "dur": dur, "author": user,
                "license": "Pixabay", "likes": likes, "downloads": dl,
                "stats": f"♥{likes} ↓{dl}", "page": "https://pixabay.com" + path,
                "preview": url, "url": url, "desc": note, "source": "pixabay"}

    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(detail, cards[: a.n * 2]))
    # Cards whose detail page failed are kept: the name and like count still tell the
    # user whether the cue is worth opening by hand. Dropping them made the whole source
    # look empty whenever Pixabay rate-limited us.
    rows = [r for r in rows if r["url"]] + [r for r in rows if not r["url"]]
    rows.sort(key=lambda r: -r["likes"])
    if not rows:
        if all(ord(c) < 128 for c in a.query):
            print("# pixabay: parsed 0 results — if the search page loads in a browser, its "
                  "markup changed (or Cloudflare is serving a challenge)", file=sys.stderr)
    return rows[: a.n]


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
                     "license": "Mixkit Free", "preview": mp3.group(1),
                     # the card only advertises the mp3 preview; Mixkit also serves the full
                     # WAV at a predictable path, which is what we actually want in an edit.
                     "wav": f"https://assets.mixkit.co/active_storage/sfx/{sid.group(1)}/"
                            f"{sid.group(1)}.wav",
                     "url": f"https://assets.mixkit.co/active_storage/sfx/{sid.group(1)}/"
                            f"{sid.group(1)}.wav",
                     "desc": "", "source": "mixkit"})
        if len(rows) >= limit:
            break
    return rows


def mixkit(a):
    """Scrape mixkit.co. Cards carry title + duration only — no ratings, no download counts.

    Mixkit's ?q= parameter returns an unrelated default list, so the keyword has to go in
    the path (/free-sound-effects/<keyword>/). The path takes one word, so a multi-word
    query ("page flip") searches its first term and then filters the results by every
    term — otherwise "card pop" came back as poker-card sounds.
    """
    terms = [t for t in re.split(r"[^a-z0-9]+", a.query.lower()) if t]
    if not terms:
        print("# mixkit: needs an English keyword — nothing to search", file=sys.stderr)
        return []
    kw = terms[0]
    try:
        rows = _mixkit_parse(fetch(f"https://mixkit.co/free-sound-effects/{kw}/").decode("utf-8", "replace"),
                             a.n * 4)
        if rows:
            strict = [r for r in rows if all(t in r["title"].lower() for t in terms)]
            if strict:
                return strict[: a.n]
            if len(terms) > 1:
                print(f"# mixkit: nothing matches all of {terms!r}; showing the "
                      f"'{kw}' category instead", file=sys.stderr)
            return rows[: a.n]
    except Exception as e:
        print(f"# mixkit: {e!r}", file=sys.stderr)
    h = fetch("https://mixkit.co/free-sound-effects/").decode("utf-8", "replace")
    return [r for r in _mixkit_parse(h, 400)
            if all(t in r["title"].lower() for t in terms)][: a.n]


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


def _kenney_available():
    """Every audio pack Kenney publishes. The category page needs a browser UA — a bare
    request gets 403. Values are slugs; the download id is just hex('assets/<slug>')."""
    try:
        h = fetch("https://kenney.nl/assets/category:Audio").decode("utf-8", "replace")
    except Exception:
        return []
    junk = {"category", "series", "tag"}
    return sorted({s for s in re.findall(r"kenney\.nl/assets/([a-z0-9-]+)", h) if s not in junk})


def ensure_kenney(slugs=None, verbose=True):
    """Download + unpack CC0 packs once, cached under ~/.cache. Defaults to the UI packs;
    pass slugs to pull others (impact-sounds, sci-fi-sounds, music-jingles, …).

    A pack counts as done only when its `.complete` marker exists. The old test was
    "directory non-empty", which accepted a half-extracted pack (measured: 5 of 10 clips
    after an interrupted unzip) and never retried it.
    """
    KENNEY.mkdir(parents=True, exist_ok=True)
    for slug in (slugs or [s for s, _ in KENNEY_PACKS]):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug or ""):
            if verbose:
                print(f"# ! refusing suspicious Kenney slug {slug!r}", file=sys.stderr)
            continue
        dest = KENNEY / slug
        if (dest / ".complete").exists():
            continue
        if verbose:
            print(f"# fetching Kenney pack '{slug}' (CC0)…", file=sys.stderr)
        u = _kenney_zip(slug)
        if not u:
            if verbose:
                print(f"# ! could not resolve Kenney pack {slug}", file=sys.stderr)
            continue
        try:
            req = urllib.request.Request(u, headers={**UA, "Referer": f"https://kenney.nl/assets/{slug}"})
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                # zip-slip: refuse members that resolve outside the pack directory
                for m in z.namelist():
                    target = (dest / m).resolve()
                    if not str(target).startswith(str(dest.resolve())):
                        raise OSError(f"zip member escapes pack dir: {m}")
                z.extractall(dest)
            (dest / ".complete").write_text("", encoding="utf-8")
        except Exception as e:
            if verbose:
                print(f"# ! Kenney pack {slug} failed: {e!r}", file=sys.stderr)
    return KENNEY


def _kenney_files():
    exts = {".ogg", ".wav", ".mp3", ".m4a", ".flac"}
    skip = {"preview"}          # each pack ships a Preview.ogg montage, not a usable clip
    out = []
    if KENNEY.exists():
        for p in KENNEY.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts and p.stem.lower() not in skip:
                out.append(p)
    return out


def _natural(s):
    """Sort key that keeps switch2 before switch10 (plain string order does not)."""
    return tuple(int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s.lower()))


def kenney(a):
    if getattr(a, "packs", False):
        avail = _kenney_available()
        got = {p.name for p in KENNEY.iterdir()
               if p.is_dir() and (p / ".complete").exists()} if KENNEY.exists() else set()
        print(f"# {len(avail)} audio packs on kenney.nl — ✓ = already indexed locally")
        for s in avail:
            print(("✓ " if s in got else "  ") + s)
        print("# add one with: kenney --fetch <slug>", file=sys.stderr)
        return []
    if getattr(a, "fetch", None):
        ensure_kenney([a.fetch])
    ensure_kenney()
    terms = [t for t in re.split(r"[^a-z0-9]+", (a.query or "").lower()) if t]
    if (a.query or "").strip() and not terms:
        # Kenney filenames are English only. Without this guard an all-CJK query leaves
        # terms empty, `if terms and not score` short-circuits, and every file matches —
        # the caller got 20 arbitrary clips back.
        print("# kenney: pack filenames are English — this query has no ASCII token to "
              "match, so nothing was searched. Try an English cue.", file=sys.stderr)
        return []
    rows = []
    for p in _kenney_files():
        stem = p.stem.lower()
        hits = [t for t in terms if t in stem]
        if terms and not hits:
            continue
        # Rank by how many distinct query terms hit, then by how much of the name they
        # cover. The old score let a single generic token ("click") outrank the exact
        # noun the user asked for ("switch").
        score = (len(hits), sum(len(t) for t in hits))
        rows.append({"key": f"kn:{p.relative_to(KENNEY).as_posix()}", "title": p.stem,
                     "dur": "?", "author": "Kenney", "license": "CC0", "preview": "",
                     "url": "", "path": str(p), "desc": f"{p.suffix.lstrip('.')} · {p.parent.name}",
                     "score": score, "source": "kenney"})
    rows.sort(key=lambda r: (-r["score"][0], -r["score"][1], _natural(r["title"])))
    return rows[: getattr(a, "n", 20)]


# ---------------------------------------------------------------- aggregate

def _is_ui(query):
    return bool(set(re.split(r"[^a-z0-9]+", query.lower())) & UI_HINTS)


def _non_ascii_warn(query):
    """All four catalogs are indexed in English. A CJK cue does not fail loudly — Pixabay
    answers it with unrelated clips (measured: 关门声 → "Confused Male Voice Huh"), which
    reads like a real result. Say so instead of letting the user trust it.

    Called from the CLI entry point rather than from search(): a user who runs
    `pixabay "关门声"` directly is the one most likely to be fooled by the noise.
    """
    if not query or not any(ord(ch) > 127 for ch in query):
        return False
    print("# ! this cue is not English. All four catalogs index English terms, so a "
          "translated cue returns noise, not matches — translate it first "
          "(e.g. 关门声 → door close, 翻页 → page turn, 点击 → click).",
          file=sys.stderr)
    return True


def search(a):
    """Run every source, then rank the way the documented workflow says."""
    order = (["kenney", "pixabay", "freesound", "mixkit"] if _is_ui(a.query)
             else ["pixabay", "freesound", "mixkit", "kenney"])
    a_sort = argparse.Namespace(**{**vars(a), "sort": "relevance", "pages": 2, "page": 1,
                                   "license": a.license, "n": a.n, "urls": a.urls})
    fns = {"kenney": kenney, "pixabay": pixabay, "freesound": freesound, "mixkit": mixkit}
    buckets = {}
    for name in order:
        try:
            buckets[name] = fns[name](a_sort)[: a.n]
        except Exception as e:
            print(f"# {name}: {e!r}", file=sys.stderr)
            buckets[name] = []

    ui = _is_ui(a.query)
    if ui and buckets.get("kenney"):
        why = "UI cue → Kenney first"
    elif ui:
        why = "UI cue, but no indexed Kenney pack matched → human-feedback first"
    else:
        why = "not a UI cue → human-feedback first"
    print(f"# query={a.query!r}  {why}")
    effective = [n for n in order if buckets.get(n)]
    print(f"# order: {' > '.join(effective) if effective else '(nothing returned)'}")
    if ui and not buckets.get("kenney"):
        print("# note: no indexed Kenney pack has a clip for this cue — the default packs "
              "are clicks/toggles/blips; try `kenney --packs` and `--fetch <slug>` for more")
    rows = []
    shown = {}
    for name in order:
        b = buckets.get(name) or []
        if not b:
            continue
        kept = _filter_dur(b, a)
        print(f"\n## {name} ({len(kept)}" + (f" of {len(b)}" if len(kept) != len(b) else "") + ")")
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
    ff = _find_tool("ffmpeg")
    if not ff:
        return False
    r = subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(src),
                        "-codec:a", "libmp3lame", "-qscale:a", "2", str(dst)],
                       capture_output=True)
    return r.returncode == 0 and dst.exists()


def get(a):
    out = Path(a.out_dir)
    try:
        out.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # WinError 183 here is "path exists as a file", not a network problem — the old
        # code let it bubble up to the generic handler and print "network error".
        sys.exit(f"cannot use {out} as an output directory: {e.strerror or e}"
                 + (" (that path is a file)" if out.is_file() else ""))
    idx = load_index()

    def one(key):
        src_tag, sep, ref = key.partition(":")
        if src_tag == "kn":
            p = KENNEY / ref
            if not p.exists():
                # The real keys look like "kn:ui-audio/Audio/click1.ogg". Typing
                # "kn:ui-audio/click1.ogg" is the obvious mistake, and "run `kenney`
                # first" sent the user round a loop that always succeeded and never
                # explained the shape. Look for the stem and say the exact key.
                want = Path(ref).stem.lower()
                hits = [f"kn:{f.relative_to(KENNEY).as_posix()}" for f in _kenney_files()
                        if f.stem.lower() == want][:3]
                if hits:
                    return key, None, "unknown key — did you mean " + " or ".join(hits) + "?"
                return key, None, ("unknown key — copy the kn: key exactly as `kenney` printed "
                                   "it (it includes the Audio/ segment)")
            # Keep the pack name in the filename: two packs can hold the same stem
            # (click1.ogg exists in both ui-audio and interface-sounds), and the old
            # "kn_<stem>" silently overwrote one with the other.
            pack = p.parent.parent.name if p.parent.name.lower() == "audio" else p.parent.name
            dst = out / f"kn_{re.sub(r'[^\w]+', '-', pack)}_{re.sub(r'[^\w]+', '-', p.stem)}{'.mp3' if _find_tool('ffmpeg') else p.suffix}"
            if not dst.exists() and not _to_mp3(p, dst):
                dst = out / f"kn_{re.sub(r'[^\w]+', '-', pack)}_{p.name}"
                if not dst.exists():
                    shutil.copy2(p, dst)
            for stale in out.glob(f"{dst.name}*.part"):
                try:
                    stale.unlink()
                except OSError:
                    pass
            return key, dst, None if dst.suffix == ".mp3" else "kept raw ogg — ffmpeg missing or conversion failed"
        if not sep or src_tag not in ("fs", "mk", "px"):
            return key, None, "unsupported key — use px:/fs:/mk:/kn:"
        r = idx.get(key)
        if not r and src_tag == "mk":
            # Mixkit serves every clip at a predictable path, so an id from a previous
            # session still downloads without re-running the search.
            r = {"title": "", "license": "Mixkit Free"}
        if not r:
            return key, None, "unknown key — search first"
        # Mixkit: try the full WAV first, then the card's preview mp3. Some ids 403 on
        # the WAV (measured: 788, 1143) while the preview is always served — without this
        # fallback those clips are undownloadable even though search listed them.
        urls = []
        if src_tag == "mk":
            urls.append(f"https://assets.mixkit.co/active_storage/sfx/{ref}/{ref}.wav")
            urls.append(f"https://assets.mixkit.co/active_storage/sfx/{ref}/{ref}-preview.mp3")
        for u in (r.get("preview"), r.get("url")):
            if u and u not in urls:
                urls.append(u)
        slug = re.sub(r"[^\w]+", "-", r["title"]).strip("-")[:40]
        last = None
        for u in urls:
            dst = out / f"{src_tag}_{ref}{'_' + slug if slug else ''}{Path(urllib.parse.urlparse(u).path).suffix}"
            if dst.exists():
                break
            # Unique per process+thread: two workers (or two `get` runs) on the same key
            # used to write one .part, interleave, and land a corrupt file that
            # dst.exists() then treated as permanently done.
            tmp = dst.parent / f"{dst.name}.{os.getpid()}.{threading.get_ident()}.part"
            try:
                tmp.write_bytes(fetch(u, timeout=300))
                try:
                    os.replace(tmp, dst)
                except PermissionError:
                    # Windows: another process holds dst open, or won the race and is
                    # mid-replace. If a complete file is there now, that is success.
                    if dst.exists() and dst.stat().st_size > 0:
                        tmp.unlink(missing_ok=True)
                        break
                    raise
                # Sweep leftovers, but only ones nobody is writing: a sibling process
                # downloads into its own pid-stamped .part, and deleting that mid-write
                # made the loser die with PermissionError. Anything touched in the last
                # 10 minutes may still be live.
                cutoff = time.time() - 600
                for stale in dst.parent.glob(f"{dst.name}*.part"):
                    try:
                        if stale.stat().st_mtime < cutoff:
                            stale.unlink()
                    except OSError:
                        pass
                break
            except Exception as e:
                last = e
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
        else:
            hint = f" — open {r['page']} by hand" if r.get("page") else ""
            msg = repr(last) if last else "no download url"
            if src_tag == "mk" and "403" in str(last):
                # Both "this id does not exist" and "the WAV is blocked" answer 403, and
                # the preview mp3 fallback already ran — so the id itself is the problem.
                msg = ("HTTP 403 on both the WAV and the preview — no such Mixkit id "
                       f"{ref}; re-run the search and copy a fresh mk: key")
            return key, None, msg + hint
        lic = r.get("license", "CC0")
        return key, dst, f"credit {r.get('author', '?')}" if lic not in ("CC0", "Mixkit Free", "Pixabay") else None

    def safe(key):
        try:
            return one(key)
        except Exception as e:  # one bad file shouldn't sink the batch
            return key, None, repr(e)

    # Freesound caps ~80 KB/s per connection, so parallelism is the only speed lever.
    ok = 0
    failed = []
    with ThreadPoolExecutor(6) as ex:
        for key, dst, note in ex.map(safe, a.keys):
            if not dst:
                failed.append(key)
                print(f"FAIL {key}: {note}")
                continue
            ok += 1
            # Measure what actually landed. The catalog duration is rounded to the second,
            # so this is the only number a short cue can be judged on. Peak is measured
            # too: a positive value means the clip clips and will distort in a mix.
            d = _ffprobe_dur(dst)
            dur = f"{d:.3f}s" if d is not None else "?s"
            pk = _peak_db(dst)
            peak = ""
            if pk is not None:
                peak = f"{pk:+.1f}dB" + ("  CLIPPING" if pk >= -0.1 else "")
            cols = [dst.name, dur] + ([peak] if peak else []) + ([f"[{note}]"] if note else [])
            print("\t".join(cols))
    if failed:
        # A partial failure used to exit 0 with the FAIL line buried in the successes.
        print(f"\n{ok} ok, {len(failed)} failed: {', '.join(failed)}")
        sys.exit(1)
    if not ok:
        sys.exit(1)      # every key failed — do not report success


# ---------------------------------------------------------------- cli

def _utf8_stdio():
    """Force UTF-8 on stdout/stderr before anything prints.

    Windows consoles default to cp936/gbk here, and the module docstring — which argparse
    echoes for --help — contains ♥ ↓ ★ →. Doing this after parse_args() was too late:
    `sfx.py --help` died with UnicodeEncodeError before the fix ever ran.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_utf8_stdio()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("query")
        p.add_argument("-n", type=int, default=8)
        p.add_argument("--urls", action="store_true")
        p.add_argument("--min-dur", type=float, metavar="SEC",
                       help="drop results shorter than this (unknown durations are kept)")
        p.add_argument("--max-dur", type=float, metavar="SEC",
                       help="drop results longer than this — the fix for a 0.2s cue "
                            "returning a 55s loop")

    s = sp.add_parser("search"); common(s)
    s.add_argument("--license", choices=FS_LICENSE, default="any"); s.set_defaults(fn=search)

    x = sp.add_parser("pixabay"); common(x)
    x.add_argument("-p", "--page", type=int, default=1)
    x.add_argument("--pages", type=int, default=3, help="relevance pages (20 each) to rank by likes")
    x.set_defaults(fn=lambda a: _fmt(pixabay(a), a))

    f = sp.add_parser("freesound"); common(f)
    f.add_argument("--license", choices=FS_LICENSE, default="any")
    f.add_argument("--sort", choices=FS_SORT, default="relevance")
    f.add_argument("-p", "--page", type=int, default=1)
    f.add_argument("--pages", type=int, default=3, help="relevance pages (15 each) to rank by downloads")
    f.set_defaults(fn=lambda a: _fmt(freesound(a), a, lic=a.license != "cc0"))

    m = sp.add_parser("mixkit"); common(m); m.set_defaults(fn=lambda a: _fmt(mixkit(a), a))

    k = sp.add_parser("kenney")
    k.add_argument("query", nargs="?", default="")
    k.add_argument("-n", type=int, default=20)
    k.add_argument("--urls", action="store_true")
    k.add_argument("--min-dur", type=float, metavar="SEC")
    k.add_argument("--max-dur", type=float, metavar="SEC")
    k.add_argument("--packs", action="store_true", help="list every Kenney audio pack and which are indexed")
    k.add_argument("--fetch", metavar="SLUG", help="download one more CC0 pack, then search it")
    k.set_defaults(fn=lambda a: _fmt(kenney(a), a))

    g = sp.add_parser("get"); g.add_argument("out_dir"); g.add_argument("keys", nargs="+"); g.set_defaults(fn=get)

    a = ap.parse_args()
    # Warn for every subcommand that takes a query, not just `search`: running
    # `pixabay "关门声"` directly returned unrelated clips with no hint at all.
    _non_ascii_warn(getattr(a, "query", "") or "")
    if a.cmd in ("pixabay", "search") or (a.cmd == "get" and any(k.startswith("px:") for k in a.keys)):
        _ensure_cffi()
    try:
        a.fn(a)
    except KeyboardInterrupt:
        sys.exit(130)
    except OSError as e:
        sys.exit(f"network error: {getattr(e, 'reason', e)}")
    except Exception as e:
        # A raw traceback tells a non-programmer nothing; SFX_DEBUG=1 brings it back.
        if os.environ.get("SFX_DEBUG"):
            raise
        sys.exit(f"{e.__class__.__name__}: {e}")


if __name__ == "__main__":
    main()
