---
name: sound
description: Find and download sound effects for videos from Pixabay, Freesound, Mixkit and Kenney, ranking by human feedback with Kenney promoted for UI sounds.
allowed-tools: Bash(python $HOME/.agents/skills/sound/scripts/*)
---
You can't hear these clips, so lean on what people who *did* hear them left behind: likes, download counts, ratings, vote counts, and the uploader's own description. Mixkit and Kenney give you a filename and a duration; that's all they have, so judge those by name and length.

```
S=$HOME/.agents/skills/sound/scripts/sfx.py
python $S search "<query>"        # all four sources, ranked for the cue
python $S pixabay "<query>"       # ♥likes ↓downloads (largest catalog, no credit needed)
python $S freesound "<query>"     # ↓downloads ★rating(votes) license description
python $S mixkit "<query>"        # title + duration only
python $S kenney "<query>"        # local CC0 pack index (first run fetches ~1 MB)
python $S kenney --packs          # list all 10 Kenney audio packs, ✓ = already indexed
python $S kenney "<query>" --fetch impact-sounds   # pull another CC0 pack, then search it
python $S get <dir> px:<id> fs:<id> mk:<id> kn:<path>   # parallel download
```

`--urls` on any search adds preview links so the user can audition.

## Which library first

Not a preference — it changes the result. Measured on the same 7-second product animation (title fly-in, four cards, a switch toggle, a page flip, a logo land), two skills differing *only* in search order were compared blind. The order below won:

1. **Human-feedback libraries first** — Pixabay (♥likes, ↓downloads) and Freesound (downloads, ratings, vote counts, uploader description). Those numbers are other people's ears standing in for yours. Pixabay goes first simply because it is much larger: a ♥2.6K whoosh there is a better starting point than anything Freesound's foley-first catalog returns for the same cue.
2. **Then Mixkit** — decent sourcing, but a title and a duration is thin evidence.
3. **Kenney last** — except for UI.

**The exception: UI sounds go to Kenney first.** On the same test the one clip that lost was the switch toggle: the Freesound pick was a real (torch) switch, well-rated, but Kenney's purpose-built UI pack beat it. `search` already applies this rule automatically — a cue containing click / switch / button / pop / toggle / ui / rollover / select / menu / tap / hover / tick / beep / notification / alert routes Kenney first; everything else routes Pixabay first. It prints the order it chose and why, so you can cite that.

## Reading the signals

- Prefer the most-liked (or most-downloaded) clip that fits the cue, and quote the numbers when proposing it. A high vote count beats a high average: ★4.4(380) is stronger evidence than ★4.9(6).
- The Freesound description is the closest thing to listening: "built-in mic" or "made with my mouth" means lo-fi; a named recorder (Zoom, Sound Devices) and a clear source ("cork from a wine bottle") mean you know what you'll get. Reject clips whose description shows a different source than the cue, however popular.
- Licenses: **Pixabay needs no credit**, **Kenney packs are CC0**, Mixkit is free to use, Freesound is CC0 / BY (needs a credit — `get` prints it) / avoid BY-NC for anything commercial (`--license cc0|by` filters).
- Popularity says nothing about fit: a widely downloaded "thud" can be a 3 s cinematic rumble. Check the duration, and measure with ffmpeg (tail length, where the energy sits) before trusting a top hit.
- Match the transition, not just the noun. A card pop wants a short click under ~0.5 s; a whoosh for a page flip wants 0.3–0.8 s with movement.

## Practical notes

- **Formats differ by source, and it matters.** Mixkit downloads the full `.wav` (the card only advertises an mp3 preview — the script swaps in the WAV path). Kenney ships `.ogg`, which most editors refuse, so `get` converts to `.mp3` with ffmpeg automatically; without ffmpeg on PATH it keeps the raw `.ogg` and says so. Pixabay and Freesound give mp3.
- Freesound caps ~80 KB/s per connection, so put every key in one `get` — it downloads in parallel (6 workers).
- **Pixabay sits behind Cloudflare.** A plain request gets "Just a moment…" (HTTP 403), so the script impersonates Chrome's TLS fingerprint through `curl_cffi`, installed once into `~/.cache/sfx-sources/venv` on the first Pixabay call (~10 s). Nothing global is touched. If it starts returning 403 anyway, Cloudflare tightened — fall back to reading the search page by hand.
- Kenney packs are fetched once into `~/.cache/sfx-sources/kenney/` and re-indexed from disk afterwards, so repeat searches are instant and offline. Only the two UI packs come by default; Kenney publishes ten audio packs — `kenney --packs` lists them (impact-sounds, sci-fi-sounds, music-jingles, rpg-audio, casino-audio, digital-audio, two voiceover packs), and `--fetch <slug>` pulls one in. Worth doing when the cue is impacts, sci-fi, or game audio: those packs are CC0, purpose-built, and consistent as a set.
- Freesound and Pixabay both work over a direct connection here; no proxy is required. `clash_freesound.py` is macOS/ClashX-only and does nothing on Windows — skip it.
- On Windows the console defaults to cp936, which mangles ♥ ↓ ★ →; the script reconfigures stdout to UTF-8 so the tables read correctly.
