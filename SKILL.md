---
name: sound
description: Find and download sound effects for videos from Pixabay, Freesound, Mixkit and Kenney, ranking by human feedback with Kenney promoted for UI sounds.
allowed-tools: Bash(python $HOME/.agents/skills/sound/scripts/*)
---
You can't hear these clips, so lean on what people who *did* hear them left behind: likes, download counts, ratings, vote counts, and the uploader's own description. Mixkit gives a title and a duration; Kenney gives only a filename, so judge that by name alone.

```
S=$HOME/.agents/skills/sound/scripts/sfx.py
python $S search "<query>"        # all four sources, ranked for the cue
python $S search "<query>" --max-dur 0.8   # short one-shots only (card pops, clicks)
python $S pixabay "<query>"       # ♥likes ↓downloads (largest catalog, no credit needed)
python $S freesound "<query>"     # ↓downloads ★rating(votes) license description
python $S mixkit "<query>"        # title + duration only
python $S kenney "<query>"        # local CC0 pack index (first run fetches ~1.8 MB)
python $S kenney --packs          # list all 10 Kenney audio packs, ✓ = already indexed
python $S kenney "<query>" --fetch impact-sounds   # pull another CC0 pack, then search it
python $S get <dir> px:<id> fs:<id> mk:<id> kn:<path>   # parallel download
```

`--urls` on any search adds preview links so the user can audition.

**`get` prints the measured duration and peak level of every file it saves.** Trust those numbers, not the ones in the search listing — see "Durations lie" below. A peak at or above `-0.1 dB` is flagged `CLIPPING`: the clip already distorts at unity gain and will sound worse once placed in a mix (measured on a popular Pixabay whoosh: `+1.5dB CLIPPING`). A batch that partly fails ends with `N ok, M failed` and exits non-zero.

## Which library first

Not a preference — it changes the result. Measured on the same 7-second product animation (title fly-in, four cards, a switch toggle, a page flip, a logo land), two skills differing *only* in search order were compared blind. The order below won:

1. **Human-feedback libraries first** — Pixabay (♥likes, ↓downloads) and Freesound (downloads, ratings, vote counts, uploader description). Those numbers are other people's ears standing in for yours. Pixabay goes first simply because it is much larger: a ♥2.6K whoosh there is a better starting point than anything Freesound's foley-first catalog returns for the same cue.
2. **Then Mixkit** — decent sourcing, but a title and a duration is thin evidence.
3. **Kenney last** — except for UI.

**The exception: UI sounds go to Kenney first.** On the same test the one clip that lost was the switch toggle: the Freesound pick was a real (torch) switch, well-rated, but Kenney's purpose-built UI pack beat it. `search` applies this automatically: a cue containing click / switch / button / pop / toggle / ui / rollover / hover / select / menu / tap / tick / beep / cursor / notification / alert / confirm / error / success / check / back / close / drop / bong / glitch / blip is treated as an interface cue and Kenney is searched first. **If the indexed packs have no matching file, it falls back to Pixabay and says so** — only about a third of those words actually have a clip in the two default packs, so expect the fallback. It prints the order it chose and why, so you can cite that.

Note the list is deliberately narrow. It holds *interface* cues only. Transition cues — whoosh, slide, swipe, riser — are **not** in it, because Kenney's packs contain no such clips: routing them to Kenney just returns nothing and wastes a round trip.

## Durations lie

Every catalog rounds, and the rounding is large enough to make a short cue unjudgeable:

| Source | What it prints | Measured | Error |
|---|---|---|---|
| Pixabay | `1s` | 0.552 s | −45% |
| Pixabay | `1s` | 1.200 s | +20% |
| Mixkit | `0:01s` | 0.452 s | −55% |
| Kenney | `?` | — | none at all |

So: **never pick a sub-second clip from the listing.** Either run `get` and read the measured duration it prints, or narrow the search with `--max-dur` and let the filter do the first pass. `--min-dur` / `--max-dur` are applied to the printed view only — every result is still cached, so a filtered-out clip can still be downloaded by key afterwards.

`--max-dur` allows some slack on purpose. Because the listing rounds *up*, a hard bound would reject a 0.479 s card pop printed as `0:01s` — the exact clip the flag exists to find. The allowance scales with the bound (0.35 s for a 0.3 s cue, 0.4 s for 0.8 s, capped at 1.0 s), so short cues stay tight while long ones stay usable. It is still an approximation: `get` prints the real length, which is the number to trust.

Ranking is another trap: all four sources sort by popularity, and popularity is an *inverse* signal for short one-shots — a 55-second paper-rustle loop out-likes the 0.45-second page turn you actually want. Combine `--max-dur` with a popularity-sorted list and you get the usable short clips with the crowd's endorsement on top.

## Reading the signals

- Prefer the most-liked (or most-downloaded) clip that fits the cue, and quote the numbers when proposing it. A high vote count beats a high average: ★4.4(380) is stronger evidence than ★4.9(6).
- The Freesound description is the closest thing to listening: "built-in mic" or "made with my mouth" means lo-fi; a named recorder (Zoom, Sound Devices) and a clear source ("cork from a wine bottle") mean you know what you'll get. Reject clips whose description shows a different source than the cue, however popular.
- Licenses: **Pixabay needs no credit**, **Kenney packs are CC0**, Mixkit is free to use, Freesound is CC0 / BY (needs a credit — `get` prints it) / avoid BY-NC for anything commercial (`--license cc0|by` filters).
- Popularity says nothing about fit: a widely downloaded "thud" can be a 3 s cinematic rumble. Check the duration, and measure with ffmpeg (tail length, where the energy sits) before trusting a top hit.
- Match the transition, not just the noun. A card pop wants a short click under ~0.5 s; a whoosh for a page flip wants 0.3–0.8 s with movement.

## Practical notes

- **Formats differ by source, and it matters.** Mixkit tries the full `.wav` first and falls back to the card's preview mp3 — some ids answer 403 on the WAV while the preview is always served, so without the fallback those clips look downloadable and then fail. Kenney ships `.ogg`, which most editors refuse, so `get` converts to `.mp3` with ffmpeg automatically. Both `ffmpeg` and `ffprobe` are looked up in PATH and then in the usual install directories; only when neither is found does `get` keep the raw `.ogg` and print `?s` for the duration. Pixabay and Freesound give mp3.
- Kenney downloads keep the pack name in the filename (`kn_ui-audio_click1.mp3`), so a clip stays traceable to the pack it came from.
- Freesound caps ~80 KB/s per connection, so put every key in one `get` — it downloads in parallel (6 workers).
- **A `kn:` key is confined to the Kenney cache.** Anything that resolves outside it is rejected, so a hand-typed `kn:../../something` fails rather than reading an arbitrary file. Copy keys exactly as `kenney` printed them; the `Audio/` segment is part of the key.
- `--pages` is capped at 20. Beyond a handful of pages the catalogs repeat themselves, and walking Pixabay deep enough triggers its rate limit mid-run, which loses everything already fetched.
- **Pixabay sits behind Cloudflare.** A plain request gets "Just a moment…" (HTTP 403), so the script impersonates Chrome's TLS fingerprint through `curl_cffi`, installed once into `~/.cache/sfx-sources/venv` on the first Pixabay call (~10 s). Nothing global is touched. If it starts returning 403 anyway, Cloudflare tightened — fall back to reading the search page by hand.
- **Pixabay rate-limits (HTTP 429) under rapid repeated searching.** The script backs off 8/16 s and says so. If it still 429s, Pixabay results come back as name + like count with a `detail unavailable` note instead of vanishing — that means the mp3 URL could not be fetched, so open the `page` link by hand or retry in a minute. Do not hammer it: batch one `search` call rather than several `pixabay` calls in a row.
- Kenney packs are fetched once into `~/.cache/sfx-sources/kenney/` and re-indexed from disk afterwards, so repeat searches are instant and offline. A pack counts as installed only when its `.complete` marker exists, so an interrupted unzip is retried instead of being silently accepted as done. Only the two UI packs come by default; Kenney publishes ten audio packs — `kenney --packs` lists them (impact-sounds, sci-fi-sounds, music-jingles, rpg-audio, casino-audio, digital-audio, two voiceover packs), and `--fetch <slug>` pulls one in. Worth doing when the cue is impacts, sci-fi, or game audio: those packs are CC0, purpose-built, and consistent as a set.
- **Kenney filenames are English.** An all-CJK query matches nothing, and the script says so rather than returning arbitrary files. Translate the cue before searching that source.
- **License check before commercial use.** Freesound's default filter is `any`, which can return BY-NC — not usable commercially. Use `--license by` (CC0 + Attribution) or `--license cc0` when the output is going into paid work. Pixabay needs no credit, Kenney is CC0, Mixkit is free to use.
- Freesound and Pixabay both work over a direct connection here; no proxy is required.
- **All four catalogs index English terms.** A non-English cue does not fail loudly: Pixabay answers it with unrelated clips (measured: 关门声 → "Confused Male Voice Huh"), which reads like a real result. The script warns on stderr; translate the cue first (关门声 → door close, 翻页 → page turn, 点击 → click, 卡片弹出 → pop).
- On Windows the console defaults to cp936, which mangles ♥ ↓ ★ →; the script reconfigures stdout to UTF-8 at import time, before argparse can print `--help`, which used to die on the ♥ in this file's own docstring.
- **When a source returns nothing, check whether it actually failed.** A parse that matches zero cards prints a warning to stderr instead of returning a silent empty list, so "no results" and "the site changed its markup" are distinguishable. If a source that normally works suddenly returns nothing, suspect the site, not the query.
