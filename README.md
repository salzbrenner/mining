# Mining

A local tool for a Japanese sentence-mining Anki workflow: ingests YouTube
videos, scans their subtitles for vocabulary not already in your deck,
and lets you review/select new cards before adding them — with generated
audio (VOICEVOX), definitions (JMdict), and furigana filled in automatically.
It also handles field-mapped importing from other decks, an on-demand
`.apkg` backup of your deck, and an audit of notes missing required fields.

Works directly against a live Anki collection via the AnkiConnect add-on —
nothing here touches Anki's database file directly.

See [`SPEC.md`](./SPEC.md) for the full design/architecture writeup.

## Prerequisites

- **Anki** desktop, with the **AnkiConnect** add-on installed (Tools >
  Add-ons > Get Add-ons in Anki, code `2055492159`) and Anki running
  whenever you use this tool.
- **[uv](https://docs.astral.sh/uv/)** — manages the Python version and
  dependencies for you; nothing else to install manually.
- **ffmpeg** on your `PATH` (e.g. `brew install ffmpeg`) — used for audio
  clipping.
- A note type with the same field layout as the "Lapis" note type
  (`Expression`, `ExpressionReading`, `Sentence`, `SentenceAudio`,
  `MainDefinition`, etc.) on the deck you point this at. `app/config.py`'s
  `TARGET_DECK`/`NOTE_TYPE` say which deck/note type the tool operates on —
  change them if yours are named differently.
- Optional, for full functionality:
  - **[VOICEVOX](https://voicevox.hiroshiba.jp/)**, installed and running,
    for `ExpressionAudio` generation.
  - A JMdict term-bank and a CC-100 frequency-bank dictionary, both in
    Yomitan's zip format, dropped into `data/dictionaries/` — required for
    the SRT vocabulary scanner (§7 of `SPEC.md`).

## Setup

```sh
uv sync
```

## Run

```sh
uv run python main.py
```

Opens on `http://127.0.0.1:8123`. Anki (with AnkiConnect) needs to already
be running. On first start, your local `config/*.yaml` files (ignore list,
voice exclusions, required fields) are generated from the tracked
`.yaml.example` templates if they don't already exist — see `.gitignore`
for why those aren't tracked directly (they end up holding your personal
word/voice choices).
