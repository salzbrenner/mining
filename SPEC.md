# Mining — Design Notes

A local tool for a Japanese sentence-mining Anki workflow, working directly
against a live `Mining` deck via AnkiConnect. This describes the system as
it exists today; it's not a historical build log — check git history for
that once this is committed. Written to be read alongside the code, not
instead of it: file paths are given throughout so you can jump straight to
the implementation.

## 1. What this is

Two halves:

1. **Anki side** — the `Mining` deck, using a `Lapis`-compatible note type
   (see §2 for the exact field list). Anki + AnkiConnect are the source of
   truth; nothing here touches the collection file directly.
2. **Manager web app** — a local FastAPI server (server-rendered Jinja2 +
   HTMX, no SPA, no build step) that talks to AnkiConnect, downloads/manages
   YouTube videos, scans their subtitles for new vocabulary, generates
   audio/definitions/furigana, and audits the deck for incomplete cards.
   It's a tool *around* the deck, not a replacement for Anki review.

Single user, localhost only (`main.py` binds `127.0.0.1`, never `0.0.0.0`).
No auth, no external exposure — that's a deliberate scope boundary, not an
oversight; see §8 for what that assumption protects against and what it
doesn't.

## 2. Anki side

- Deck: `Mining` (`TARGET_DECK` in `app/config.py`). `SOURCE_DECK` is the
  same value — it only still exists because `app/services/clone.py` (see
  §7) imports it separately.
- Note type: `Lapis` (`NOTE_TYPE` in `app/config.py`). Relevant fields:
  `Expression`, `ExpressionReading`, `ExpressionFurigana`, `ExpressionAudio`,
  `Sentence`, `SentenceFurigana`, `SentenceAudio`, `MainDefinition`,
  `Glossary`, `Frequency`, `FreqSort`, `SourceVideo`, `SourceTimestamp`
  (the last two are additions this tool needs — add them to your note type
  if they're not already there; the tool reads the field list dynamically
  via `modelFieldNames`, so no code changes are needed either way).
- `Expression` holds the **matched dictionary headword**, not raw inflected
  surface text — e.g. highlighting `行って` in Yomitan resolves to
  `Expression = 行く`. Multi-word idioms that are themselves JMdict entries
  (like `行ってきます`, "I'm off/see you later") get stored as the whole
  phrase, since that's the headword Yomitan resolved to. This matters for
  §5's matching design: the existing-notes dedup baseline is already
  headwords, no extra normalization needed.
- Media (`ExpressionAudio`, etc.) lives in the shared, per-profile
  `collection.media` folder, not per-deck.

## 3. Architecture

```
┌──────────────────┐   AnkiConnect (HTTP, localhost:8765)
│  Anki desktop     │◄─────────────────────────────┐
│  + AnkiConnect    │                               │
│  - Mining deck    │                               │
└──────────────────┘                               │
                                                     │
┌────────────────────────────────────────────────────────────────┐
│  Manager web app (FastAPI, localhost:8123, single process)      │
│                                                                    │
│  Import   Videos (yt-dlp)   Scan (SudachiPy+JMdict)   Audit       │
│  Backfill (VOICEVOX)   Ignore list   Voice exclusions   Backup    │
└────────────────────────────────────────────────────────────────┘
        │
        ▼
  data/ (videos, audio, srt, per-video metadata, dictionaries, backups)
```

No persistent cache of Anki state: every read (dedup baselines, the
missing-field audit) queries AnkiConnect live via `findNotes` + batched
`notesInfo` (chunked to ~500 notes/request). Simpler and never stale; the
tradeoff only matters at a much higher request volume or if a client needed
deck state without Anki desktop open, neither of which applies here.

## 4. Features

### Import (field-mapped, any deck → `Mining`)
`/import`, `app/routes/importer.py`, `app/services/importer.py`.

Pick a source deck → the tool reads its note type's field list → map each
source field to a `Lapis` field (or skip) → import. Dedup is a simple
exact-match on the mapped `Expression` value against `Mining`'s existing
Expression set (not the dictionary-headword matcher §5 uses — an
acknowledged inconsistency, see §8). `deck_name` is validated against the
real deck list before use (§8.1 explains why that validation exists).

### Videos (YouTube ingestion)
`/videos`, `app/routes/videos.py`, `app/services/youtube.py`.

Paste a URL → `yt-dlp` downloads **audio only** (`ba/b` format, no video)
plus Japanese subtitles (prefers a manual/human track, falls back to
auto-generated). No video is ever stored: `SourceTimestamp` links straight
back to the moment on YouTube for rewatching, so a local copy doesn't earn
its disk cost, and a future screenshot-for-`Picture` feature can resolve a
fresh direct stream URL on demand via yt-dlp and grab one frame with ffmpeg
without storing anything either (not yet built).

Stored under `data/videos/<video_id>/`: `audio.mp3`, `ja.srt`, `meta.json`
(title, uploader, upload date, source URL, duration, which subtitle track
type was used). `video_id` is validated against a strict character-class
pattern before it's ever used in a filesystem path (`is_valid_video_id` in
`youtube.py`) — see §8.1.

### Scan (SRT → new vocabulary)
`/videos/{id}` → "Preview new vocabulary", `app/services/scan.py` +
`app/services/matcher.py`.

Dry-run by default: **Scan** parses the video's `ja.srt`, matches it
against `Mining`'s existing headwords (§5), and returns a preview
checklist — nothing is written to Anki yet. Each row shows the matched
headword, its reading/POS, its CC-100 frequency, the source subtitle line,
and a play button that clips the corresponding audio on the fly (same
clipping logic as `SentenceAudio` below, nothing stored) so you can listen
before deciding. Rows flagged low-confidence (proper nouns, single-
character matches — often leftover fragments of a longer conjugation
chain) start unchecked; you opt them in rather than out. Headwords already
in `config/ignored_words.yaml` (§6), and candidates rarer than
`MAX_FREQUENCY_RANK` (`app/config.py`, default 40,000) or with no CC-100
frequency entry at all, are dropped from the list before you ever see it.

**Add selected to Mining** (separate, explicit action) creates one note
per checked row:
- `Expression` / `ExpressionReading` — the matched headword and its
  reading, both from §5's matcher.
- `Sentence` / `SentenceFurigana` — the subtitle line, plus its
  per-token furigana rendering (§4 "Furigana", below).
- `SourceVideo` / `SourceTimestamp` — the video's title, and a clickable
  deep link (`https://youtu.be/<id>?t=<seconds>s`) to the moment.
- `Frequency` / `FreqSort` — the CC-100 rank.
- `MainDefinition` — every JMdict sense for the headword, rendered from
  the same term bank used for matching (§4 "Definitions", below).
- `ExpressionAudio` / `SentenceAudio` — VOICEVOX synthesis + a clip from
  the video's local `audio.mp3` respectively (§4 "Audio", below). Either
  can fail independently (e.g. VOICEVOX not running) without blocking note
  creation — the field is just left blank and the failure is counted.
- Tagged `danki-yt` (`YOUTUBE_IMPORT_TAG` in `app/config.py`).
- Everything else left blank, picked up by the audit (below).

Idempotent: re-scanning a video you've already committed from previews
nothing new, since the committed headwords are now part of the dedup
baseline.

### Audit (missing-field report + audio backfill)
`/audit`, `app/services/audit.py` + `app/services/audio_backfill.py`.

Scans all of `Mining` live and lists notes missing any field named in
`config/required_fields.yaml` (§6), grouped by which field(s) are missing.
The same page has a **backfill** action: for notes missing
`ExpressionAudio`/`SentenceAudio` specifically, synthesizes both directly
from the note's own Expression/Sentence text via VOICEVOX (there's no
source video to clip from for most of these — the field only clips from a
real video during Scan commit, above). A random voice is picked per note
(same voice for both fields on that note) for variety, excluding whatever's
in `config/excluded_voices.yaml` (§6, managed at `/voices`). HTML in
`Sentence` (e.g. the `<b>` around the target word) is stripped before
synthesis — sent raw, VOICEVOX will try to pronounce the literal tag text.
Never overwrites a field that already has content. Processed in batches
(default 30/click) since bulk TTS adds up — no progress feedback exists
for a single huge run, so keep it bounded instead.

### Backup
`/backup`, `app/services/backup.py`.

On-demand `.apkg` export of `Mining` via AnkiConnect's `exportPackage`
with `includeSched: true` — a real, restorable snapshot (notes, media,
*and* full review/scheduling history), timestamped into `data/backups/`
(gitignored; these get large — confirmed ~200-300MB for a collection this
size). Not automatic. This is the safety net for working directly on
`Mining` instead of a separate staging deck (§7).

### Ignore list
`/ignored-words`, `config/ignored_words.yaml`, `app/services/ignore_list.py`.

Headwords permanently excluded from every future Scan. Distinct from the
frequency cutoff above: this is for words you already know fluently that
keep surfacing because they were never mined via Yomitan (i.e. never
looked up, so never added) — a frequency-based filter alone can't catch
that, since a word you already know can still be common enough to clear
the cutoff.

## 5. Word matching / dictionary-headword design

Goal: dedup behavior that agrees with how you already mine via Yomitan —
matching against real dictionary **headwords**, the same unit `Expression`
already stores (§2) — without literally running the Yomitan browser
extension (it exposes no local API; that's what AnkiConnect is for on the
Anki side, but Yomitan has no equivalent).

Since `Expression` is already a headword, naive per-token lemmatization
isn't enough by itself — Yomitan's actual behavior is a **longest-match
scan against its loaded dictionaries**, which is what lets it resolve a
whole idiom like `行ってきます` to one entry instead of three separate
tokens. `app/services/matcher.py` approximates that:

1. **Required input**: a JMdict-format Yomitan term-bank zip
   (`term_bank_*.json`), loaded once into an in-memory headword set
   (`app/services/dictionaries.py` `load_term_headwords`). Without this
   there's no reliable way to tell "is this span a real headword" at all.
2. **Candidate generation**: SudachiPy (mode C, longest/compound
   segmentation) tokenizes each SRT line, supplying per-token surfaces and
   dictionary forms.
3. **Longest-match resolution**: at each position, try the longest run of
   consecutive tokens first — checking the **deinflected form before the
   raw surface** at each span length (not the other way around; see the
   `決める`/`決め` bug note below) — against the JMdict headword set,
   falling back to shorter spans down to a single token.
4. **Existing-deck baseline**: `Mining`'s current `Expression` values are
   the covered-headword set directly, no normalization needed.
5. **New-word detection**: any resolved headword not in that set is a
   candidate.
6. **Known limitation**: this is an approximation, not Yomitan itself — a
   greedy longest-match without Yomitan's actual deinflection-reason engine
   will occasionally disagree with it on unusual conjugations or ambiguous
   segmentation. Vendoring Yomitan's own open-source deinflection module
   (e.g. as a small local Node service) would close that gap fully; not
   done.

**Real bug found via testing, worth understanding if this ever regresses**:
the per-span check originally tried the raw surface text *before* the
deinflected form. Highlighting `決めてた` in Yomitan resolves to `決める`
(the verb) — but `決め` is *also* a separate, real JMdict noun entry that
happens to match the raw (inflected) surface. Checking surface first
grabbed that coincidental noun match and stopped before ever trying
deinflection. The fix (try deinflected form first, fall back to surface)
is a pure improvement with no downside for tokens that aren't inflected at
all, since in that case the two checks are identical.

A second, unrelated limitation: JMdict indexes some entries under their
kanji orthography only (e.g. `来る`), while SudachiPy's `dictionary_form()`
returns kana when the source token itself was written in kana (`くる`) —
so a kana-written auxiliary verb can fail to match even though its kanji
equivalent is a real headword. Not fixed; would need checking kanji-
normalized variants against readings, not just reordering a check.

### Furigana rendering
`app/services/furigana.py`, used for `SentenceFurigana` at Scan-commit
time.

Per-token kanji/okurigana splitting into Anki's `漢字[かんじ]` bracket
format (the same convention Yomitan uses for `ExpressionFurigana`), using
SudachiPy's per-token surface + reading. Two real bugs found by checking
actual *rendered card HTML* via AnkiConnect's `cardsInfo` (not just the
stored field value — this is what caught both):

1. **Wrong reading for inflected tokens.** The reading has to come from
   the *resolved* headword, not the raw inflected surface —
   `起き`+`る` → `起きる` needs reading `おきる`, but naively concatenating
   each token's own `reading_form()` gives `おき` (the inflected stem's
   reading), not the dictionary form's. Fixed by re-tokenizing the
   dictionary form itself to get its correct reading when a match
   substituted it.
2. **Missing delimiter between bracket groups.** Anki's `{{furigana:}}`
   filter scopes a `[reading]` bracket to the longest run of non-space
   text immediately before it. With tokens concatenated directly (Japanese
   has no natural word spaces), one bracket group swallowed an entire
   preceding phrase instead of just the one kanji it belonged to. Fixed by
   inserting a space before each bracketed group.

Notably, the `Lapis` card's *Front* template shows nothing for the
sentence at all when `SentenceFurigana` is empty (no fallback to plain
`Sentence` there, unlike the Back template) — so this isn't cosmetic, it's
required for the front of an auto-created card to show sentence context at
all.

### Definition rendering
`app/services/dictionaries.py` `render_main_definition()`, used for
`MainDefinition` at Scan-commit time.

Renders every JMdict sense for the matched headword into HTML, from the
same term bank already loaded for matching, reusing JMdict-yomitan's own
structured-content schema (each sense's glossary is a nested
tag/content/data tree; rendered recursively into real HTML tags). JMdict's
own embedded example-sentence blocks (`data.content == "examples"`) are
deliberately skipped — `Sentence` already holds a real, video-sourced
example, so a second one would just be clutter.

## 6. Config & data layout

```
hanki/
  app/                        # FastAPI app: routes, services, templates
  data/
    videos/<video_id>/        # audio.mp3, ja.srt, meta.json
    dictionaries/             # user-provided Yomitan dictionary zips
                               #   (CC-100 frequency bank + JMdict term bank)
    backups/                  # timestamped .apkg exports
  config/
    required_fields.yaml       # gitignored -- personal, see .example
    ignored_words.yaml         # gitignored -- personal, see .example
    excluded_voices.yaml       # gitignored -- personal, see .example
    *.yaml.example             # tracked templates for the above
  SPEC.md
```

`config/*.yaml` hold real usage data (your specific vocabulary gaps, voice
preferences) and are gitignored; `.yaml.example` counterparts are tracked
instead. `app/config.py` auto-copies each example into place on first run
if the real file doesn't exist yet (never overwrites an existing one) — a
fresh clone works without a manual copy step.

## 7. `Mining 2` (deprecated staging-deck workflow)

This tool originally worked on a separate `Mining 2` deck (cloned from
`Mining`) so the original deck was never at risk while the tool was
immature — a clone/promote dance where `Mining 2` was the scratch space
and changes got merged back manually. After extensive real use, the
two-deck workflow turned out to add more complexity than safety value, so
the tool was switched to work **directly on `Mining`**, with the Backup
feature (§4) as the safety net instead: back it up before a work session,
restore via Anki's own File > Import if something goes wrong.

`TARGET_DECK` in `app/config.py` points at `Mining` directly now (every
active feature reads this one constant). The `Mining 2` deck itself has
since been deleted from Anki entirely. The old clone/promote UI (routes,
templates) was removed from the app (unregistered in `app/main.py`) since
a same-deck "clone" doesn't make sense and the old "Clear & re-clone"
action would have been actively dangerous (it would wipe `Mining` itself)
— but `app/services/clone.py` and its templates are still in the codebase,
unreachable, in case a two-deck workflow is ever wanted again. If you're
reading this file and `Mining 2` doesn't mean anything to you, that's
correct — it's fully gone.

## 8. Known limitations & security notes

- **Single-user, localhost-only threat model.** This is the load-bearing
  assumption behind everything below: the only person who could exploit
  any of these is the tool's own operator, against their own local Anki
  collection. There's no cross-user boundary to cross, no remote exposure
  (confirmed `host="127.0.0.1"` in `main.py`, never `0.0.0.0`). If this
  code is ever extended to be multi-user or network-exposed, revisit every
  item below — none of them are safe under that model.

### 8.1 Fixed
- **`video_id` path traversal.** `video_id` (from yt-dlp's extracted info,
  and taken directly as a URL path parameter in several routes) used to
  flow unvalidated into filesystem paths (`VIDEOS_DIR / video_id`). Real
  YouTube ids are always safe, but yt-dlp supports thousands of
  non-YouTube extractors whose ids aren't guaranteed filesystem-safe, and
  a route path parameter is attacker-influenceable regardless of what any
  extractor would produce (e.g. `video_id=".."`). Fixed: `video_id` is now
  validated against a strict `^[A-Za-z0-9_-]{1,64}$` pattern
  (`is_valid_video_id` in `app/services/youtube.py`) before it's ever used
  in a path, both where `yt-dlp` first reports it and at every route that
  takes it as a path parameter.
- **`deck_name` query injection** in the field-mapped importer. The
  dropdown only ever offers real deck names, but the HTTP endpoints behind
  it accepted `deck_name` as a plain client-submitted string with no
  server-side check, interpolated directly into an AnkiConnect search
  query (`f'deck:"{deck_name}"'`) with no escaping — a value containing a
  literal `"` could break out of the intended `deck:` term and inject
  arbitrary search syntax (e.g. `Mining" OR deck:*` matches every deck,
  not just the one selected). Fixed: `deck_name` is validated against the
  real list from `anki.deck_names()` before use
  (`_validate_deck_name` in `app/services/importer.py`).

### 8.2 Known, not fixed
- **Import dedup inconsistency.** The field-mapped importer dedupes on
  exact-match `Expression` string equality, not the dictionary-headword
  matcher (§5) the Scan feature uses. A source deck with inflected surface
  forms instead of dictionary forms could import near-duplicates of
  existing headwords. Low practical impact so far since source decks
  tried tend to already store dictionary forms, but worth knowing about.
- **No incremental AnkiConnect sync.** Every read is a full live query;
  fine at current note counts and usage frequency, would need revisiting
  at much higher volume or request frequency.
- **Furigana/matcher approximation gaps** — see the "known limitation"
  and kana/kanji orthography notes in §5.

## 9. Possible future work

- `Picture` field auto-population: resolve a fresh direct YouTube stream
  URL on demand (not stored) and grab one frame with ffmpeg, matching how
  `SourceTimestamp` already avoids storing video.
- Vendor Yomitan's own deinflection module (open source) as a small local
  Node service, for byte-for-byte dictionary-form parity instead of the
  SudachiPy approximation in §5.
- Extend VOICEVOX audio generation to the field-mapped importer path too
  (currently Scan/backfill-specific).
- Close the import dedup inconsistency (§8.2) by sharing §5's matcher.
