"""Per-character dialogue parser — turns, expressive tags, voice assignment."""

from __future__ import annotations

from app.services.audio.dialogue import parse_dialogue


def test_two_host_alternating_voices():
    script = """Alex: Have you seen this?
Sam: No way, that's wild.
Alex: Right? It changed everything."""
    result = parse_dialogue(script)
    assert result.speakers == ("Alex", "Sam")
    voices = {t.speaker: t.voice_id for t in result.turns}
    # First-appearance order cycles the default voices.
    assert voices["Alex"] == "host_a" and voices["Sam"] == "host_b"
    assert len(result.turns) == 3


def test_expressive_tags_extracted_and_stripped():
    script = "Alex: [laughs] I can't believe it (excited)"
    result = parse_dialogue(script)
    turn = result.turns[0]
    assert turn.text == "I can't believe it"  # tags removed
    assert set(turn.tags) == {"laughs", "excited"}


def test_explicit_voice_mapping_wins():
    result = parse_dialogue("Host: hi\nGuest: hello", voices={"Host": "eleven_rachel", "Guest": "eleven_josh"})
    voices = {t.speaker: t.voice_id for t in result.turns}
    assert voices["Host"] == "eleven_rachel" and voices["Guest"] == "eleven_josh"


def test_continuation_line_keeps_speaker():
    script = """Alex: first thought
and a second thought on the same breath
Sam: my turn"""
    result = parse_dialogue(script)
    assert [t.speaker for t in result.turns] == ["Alex", "Alex", "Sam"]


def test_leading_line_without_speaker_is_narrator():
    result = parse_dialogue("just an opening line\nAlex: hi")
    assert result.turns[0].speaker == "narrator"


def test_tag_only_line_kept_as_expressive_beat():
    # A line that is ONLY a tag (e.g. [pause]) is a legitimate expressive beat:
    # kept with empty text + the tag so downstream TTS can render the pause.
    result = parse_dialogue("Alex: [pause]")
    assert len(result.turns) == 1
    assert result.turns[0].text == "" and result.turns[0].tags == ("pause",)
