import pytest

from vision.core.sentences import SentenceSplitter


def split_all(text: str, chunk: int = 3) -> list[str]:
    """Feed `text` in small chunks, as a stream would, then flush."""
    splitter = SentenceSplitter()
    out: list[str] = []
    for i in range(0, len(text), chunk):
        out += splitter.feed(text[i : i + chunk])
    return out + splitter.flush()


@pytest.mark.parametrize("chunk", [1, 3, 1000])
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello there. How are you?", ["Hello there.", "How are you?"]),
        ("Wow! Really? Yes.", ["Wow!", "Really?", "Yes."]),
        ("Dr. Smith is in. Ask Mr. Jones.", ["Dr. Smith is in.", "Ask Mr. Jones."]),
        ("Bring fruit, e.g. apples. Then go.", ["Bring fruit, e.g. apples.", "Then go."]),
        ("Pi is 3.14 roughly. It costs $2.50 today.", ["Pi is 3.14 roughly.", "It costs $2.50 today."]),
        ("Well... maybe not. Hmm... Okay then.", ["Well... maybe not.", "Hmm...", "Okay then."]),
        ("Wait… what", ["Wait… what"]),
        ("No trailing punctuation", ["No trailing punctuation"]),
        ('He said "stop." Then left.', ['He said "stop."', "Then left."]),
        ("J. R. R. Tolkien wrote it. Fine.", ["J. R. R. Tolkien wrote it.", "Fine."]),
        ("First line\nSecond line. Third", ["First line", "Second line.", "Third"]),
        ("Really?! Yes.", ["Really?!", "Yes."]),
        ("", []),
        ("   ", []),
    ],
)
def test_split(text: str, expected: list[str], chunk: int) -> None:
    assert split_all(text, chunk) == expected


def test_sentence_released_only_when_next_text_arrives() -> None:
    splitter = SentenceSplitter()
    assert splitter.feed("It is done.") == []
    assert splitter.feed(" Next") == ["It is done."]
    assert splitter.flush() == ["Next"]
    assert splitter.flush() == []
