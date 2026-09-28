import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
VIDEOS_DIR = DATA_DIR / "videos"
DICTIONARIES_DIR = DATA_DIR / "dictionaries"
BACKUPS_DIR = DATA_DIR / "backups"
CONFIG_DIR = BASE_DIR / "config"
REQUIRED_FIELDS_PATH = CONFIG_DIR / "required_fields.yaml"
IGNORED_WORDS_PATH = CONFIG_DIR / "ignored_words.yaml"
EXCLUDED_VOICES_PATH = CONFIG_DIR / "excluded_voices.yaml"


def _bootstrap_from_example(path: Path) -> None:
    """These three config files hold personal data (your actual ignore
    list, voice exclusions, required fields) and are gitignored -- only
    their `.example` counterparts are tracked. Copy the example into place
    on first run so a fresh clone works without a manual copy step."""
    if not path.exists():
        example = path.with_name(path.name + ".example")
        if example.exists():
            shutil.copy(example, path)


for _path in (REQUIRED_FIELDS_PATH, IGNORED_WORDS_PATH, EXCLUDED_VOICES_PATH):
    _bootstrap_from_example(_path)

ANKI_CONNECT_URL = "http://localhost:8765"
ANKI_CONNECT_VERSION = 6

# All active features (SRT scan commit, field-mapped import, missing-field
# audit, audio backfill) write to and dedupe against TARGET_DECK directly --
# per user decision, working on Mining directly with on-demand backups as
# the safety net, rather than a separate Mining 2 staging deck. SOURCE_DECK
# is kept only because the now-unused clone.py (staging-deck workflow,
# removed from the UI but left in the codebase) still imports it; both
# point at the same deck now, which is intentional, not a leftover bug.
SOURCE_DECK = "Mining"
TARGET_DECK = "Mining"
NOTE_TYPE = "Lapis"

# Applied to every note created via Phase 3 (SRT scan commit), so
# YouTube-sourced cards are identifiable/filterable in Anki's browser.
YOUTUBE_IMPORT_TAG = "danki-yt"

# Phase 3 scan: candidates rarer than this CC-100 rank (or with no
# frequency entry at all) are dropped rather than shown -- "for now", per
# user request; tune freely.
MAX_FREQUENCY_RANK = 40_000

# VOICEVOX engine (local TTS server, https://voicevox.hiroshiba.jp/) --
# generates ExpressionAudio for words that only ever appear embedded in
# continuous natural speech in the source video (clipping mid-sentence
# would sound co-articulated, not a clean isolated pronunciation).
VOICEVOX_URL = "http://localhost:50021"
VOICEVOX_SPEAKER = 21  # "剣崎雌雄 (Kenzaki Mesuo), Normal" -- change freely,
# GET /speakers on the engine lists all installed voices and their ids.

# SentenceAudio clips (from the locally-downloaded audio.mp3) are padded
# this much on each side of the SRT timestamps so words right at a
# subtitle's edge aren't cut off.
AUDIO_CLIP_PADDING_MS = 200

# YouTube's auto-generated (ASR) captions have unreliable per-cue timing --
# a cue's labeled window can be much shorter than how long that text
# actually takes to speak (confirmed against real data: a 3-second cue
# window containing a sentence, with the next real cue not starting for
# another 8 seconds). Manual/human-authored captions don't have this
# problem, so only auto-generated ones get the wider safety margin.
AUDIO_CLIP_PADDING_MS_AUTO = 1200
