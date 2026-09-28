"""Dictionary-headword matching engine (SPEC.md §5).

Approximates Yomitan's "scan and resolve to the longest matching dictionary
entry" behavior: SudachiPy segments the line, then consecutive tokens are
tried longest-span-first against the JMdict headword set (both their raw
surface text, to catch idioms like 行ってきます that JMdict lists as their
own entry, and with the final token's dictionary form substituted, to catch
ordinary inflected verbs/adjectives). A span with no JMdict match at all is
skipped rather than guessed at -- see SPEC.md §5's "known limitation" for
this approximation.
"""

from dataclasses import dataclass

from sudachipy import Dictionary, SplitMode

from app.config import MAX_FREQUENCY_RANK
from app.services import dictionaries

_MAX_SPAN_TOKENS = 5

# Top-level SudachiPy POS categories that aren't "vocabulary" for mining.
# Deliberately *not* trying to also exclude finer sub-classifications like
# "non-independent" verb usage (the い/し in している/しました): that tag is
# shared with genuine standalone vocabulary (e.g. とんでもない gets tagged
# 形容詞-非自立可能 despite being a real word), so a blanket exclusion there
# trades one kind of false positive for a worse false negative. Short
# single-token fragments are flagged low_confidence for review instead of
# silently auto-excluded -- see scan_line below.
_EXCLUDED_POS = {"助詞", "助動詞", "記号", "補助記号", "空白"}

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


@dataclass
class Candidate:
    headword: str
    reading: str
    pos: str
    surface_text: str
    frequency: int | None
    low_confidence: bool


@dataclass
class LineScanResult:
    candidates: list[Candidate]
    token_count: int
    rare_filtered: int


def _is_content_word(pos_tuple) -> bool:
    return pos_tuple[0] not in _EXCLUDED_POS


def _pos_label(pos_tuple) -> str:
    return "-".join(p for p in pos_tuple[:2] if p != "*")


def _reading_for(chunk, used_dictionary_form: bool) -> str:
    """Reading of the resolved headword, not the raw inflected surface.

    When the match substituted the last token's dictionary form (e.g.
    起き+る -> 起きる), its *reading* must come from that dictionary form
    too (おきる), not from reading_form() of the inflected surface (which
    would wrongly give おき) -- found via testing against real subtitle
    text, see SPEC.md §5.
    """
    if not used_dictionary_form:
        raw = "".join(t.reading_form() for t in chunk)
    else:
        last_dform_tokens = list(
            _get_tokenizer().tokenize(chunk[-1].dictionary_form(), SplitMode.C)
        )
        last_reading = "".join(t.reading_form() for t in last_dform_tokens)
        raw = "".join(t.reading_form() for t in chunk[:-1]) + last_reading
    return _katakana_to_hiragana(raw)


def scan_line(text: str) -> LineScanResult:
    headwords = dictionaries.load_term_headwords()
    freqs = dictionaries.load_frequencies()
    tokens = list(_get_tokenizer().tokenize(text, SplitMode.C))

    results: list[Candidate] = []
    rare_filtered = 0
    i = 0
    n = len(tokens)
    while i < n:
        matched_term = None
        matched_span = 1
        used_dictionary_form = False
        max_span = min(_MAX_SPAN_TOKENS, n - i)
        for span in range(max_span, 0, -1):
            chunk = tokens[i : i + span]
            # Deinflected form checked *before* the raw surface: if the last
            # token shows signs of conjugation (e.g. 決め from 決めてた), that's
            # a strong signal the intended headword is the verb/adjective
            # being conjugated (決める), not some unrelated noun that happens
            # to share the same stem spelling (決め is itself a separate real
            # JMdict entry). Checking surface first, as this used to, grabbed
            # that coincidental noun match and stopped before ever trying the
            # deinflected form -- found via testing against real subtitle
            # text (Yomitan correctly resolves 決めてた -> 決める; this engine
            # was resolving it to 決め). When the last token isn't inflected,
            # dict_concat == surface_concat anyway, so this reordering is a
            # pure fix with no downside for the uninflected case.
            dict_concat = (
                "".join(t.surface() for t in chunk[:-1]) + chunk[-1].dictionary_form()
            )
            if dict_concat in headwords:
                matched_term = dict_concat
                matched_span = span
                used_dictionary_form = dict_concat != "".join(t.surface() for t in chunk)
                break
            surface_concat = "".join(t.surface() for t in chunk)
            if surface_concat in headwords:
                matched_term = surface_concat
                matched_span = span
                used_dictionary_form = False
                break

        if matched_term is None:
            token = tokens[i]
            dform = token.dictionary_form()
            if dform in headwords and _is_content_word(token.part_of_speech()):
                matched_term = dform
                matched_span = 1
                used_dictionary_form = dform != token.surface()
            else:
                # No JMdict headword resolves here at all -- proper noun,
                # mis-segmentation, or just not in the dictionary. Skip
                # rather than invent a card for it (SPEC.md §5).
                i += 1
                continue

        chunk = tokens[i : i + matched_span]
        pos = chunk[-1].part_of_speech()
        if not _is_content_word(pos):
            i += matched_span
            continue

        freq = freqs.get(matched_term)
        if freq is None or freq > MAX_FREQUENCY_RANK:
            # Rarer than the cutoff (or not in the frequency dictionary at
            # all, which means "rarer than the rarest ranked word") --
            # dropped entirely rather than shown, per user request.
            rare_filtered += 1
            i += matched_span
            continue

        reading = _reading_for(chunk, used_dictionary_form)
        # Single-character single-token matches are disproportionately
        # fragments of a larger conjugation chain that happen to also be an
        # obscure standalone JMdict entry (e.g. 自, い) -- not excluded
        # (some are legitimate, e.g. 目/手), just deferred to review.
        is_single_char_fragment = matched_span == 1 and len(matched_term) == 1
        results.append(
            Candidate(
                headword=matched_term,
                reading=reading,
                pos=_pos_label(pos),
                surface_text="".join(t.surface() for t in chunk),
                frequency=freq,
                low_confidence=("固有名詞" in pos) or is_single_char_fragment,
            )
        )
        i += matched_span

    return LineScanResult(candidates=results, token_count=n, rare_filtered=rare_filtered)
