"""Generates `SentenceFurigana` in Anki's bracket format (漢字[かんじ]),
matching how Yomitan populates `ExpressionFurigana` (e.g.
行ってきます[いってきます]) and what the Lapis card templates expect
({{furigana:SentenceFurigana}}). The Front template shows *nothing* for the
sentence when this field is empty -- no fallback to plain `Sentence` there
(only the Back template has that fallback) -- so this isn't cosmetic, it's
needed for the front of auto-created cards to show sentence context at all.
"""

from sudachipy import Dictionary, SplitMode

_tokenizer = None


def _get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = Dictionary().create()
    return _tokenizer


def _katakana_to_hiragana(text: str) -> str:
    return "".join(
        chr(ord(ch) - 0x60) if "ァ" <= ch <= "ヶ" else ch for ch in text
    )


def _has_kanji(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


def _token_furigana(surface: str, reading: str) -> str:
    if not surface or not reading or not _has_kanji(surface):
        return surface
    if surface == reading:
        return surface
    # Longest common kana suffix (okurigana) stays outside the brackets --
    # e.g. surface="決め" reading="きめ" -> "決[き]め", not "決め[きめ]".
    # A kanji character can never match a kana one, so this never eats into
    # the kanji portion itself.
    common = 0
    while (
        common < len(surface)
        and common < len(reading)
        and surface[-(common + 1)] == reading[-(common + 1)]
    ):
        common += 1
    kanji_part = surface[: len(surface) - common]
    reading_part = reading[: len(reading) - common]
    suffix = surface[len(surface) - common :]
    if not kanji_part or not reading_part:
        return surface
    return f"{kanji_part}[{reading_part}]{suffix}"


def sentence_to_furigana(text: str) -> str:
    tokens = _get_tokenizer().tokenize(text, SplitMode.C)
    parts = []
    for t in tokens:
        surface = t.surface()
        reading = _katakana_to_hiragana(t.reading_form())
        rendered = _token_furigana(surface, reading)
        if rendered != surface and parts:
            # A bracketed group (kanji[reading]) needs a delimiter before
            # it, or Anki's {{furigana:}} filter scopes the reading to the
            # longest run of non-space text before the bracket -- with no
            # delimiter, that swallows everything back to the start of the
            # sentence (verified: without this, an entire preceding phrase
            # got wrongly absorbed into one ruby group instead of just the
            # one kanji it belonged to).
            parts.append(" ")
        parts.append(rendered)
    return "".join(parts)
