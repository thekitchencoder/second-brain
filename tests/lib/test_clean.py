import pytest
from lib.clean import extract_frontmatter, clean_content, chunk_text


def test_extract_frontmatter_present():
    doc = "---\ntitle: Test\ntags: [foo, bar]\n---\n\nBody text here."
    meta, content = extract_frontmatter(doc)
    assert meta["title"] == "Test"
    assert meta["tags"] == ["foo", "bar"]
    assert content.strip() == "Body text here."


def test_extract_frontmatter_absent():
    doc = "No front matter here."
    meta, content = extract_frontmatter(doc)
    assert meta == {}
    assert content == "No front matter here."


def test_clean_strips_ascii_art():
    content = "Real text.\n\n───────────────────\n\nMore text."
    result = clean_content(content)
    assert "───" not in result
    assert "Real text." in result
    assert "More text." in result


def test_clean_strips_box_drawing_lines():
    content = "Intro.\n\n+-------+-------+\n| col1  | col2  |\n+-------+-------+\n\nOutro."
    result = clean_content(content)
    assert "+-------+" not in result


def test_clean_collapses_code_blocks():
    content = "Text before.\n\n```python\ndef foo():\n    return 42\n```\n\nText after."
    result = clean_content(content)
    assert "def foo" not in result
    assert "[code block: python]" in result
    assert "Text before." in result
    assert "Text after." in result


def test_clean_collapses_code_block_no_lang():
    content = "Text.\n\n```\nsome code\n```\n\nMore."
    result = clean_content(content)
    assert "some code" not in result
    assert "[code block]" in result


def test_clean_simplifies_tables():
    content = "Intro.\n\n| Col A | Col B |\n|-------|-------|\n| val1  | val2  |\n\nOutro."
    result = clean_content(content)
    assert "|-------|" not in result
    assert "Col A" in result
    assert "val1" in result


def test_clean_collapses_whitespace():
    content = "Line one.\n\n\n\n\nLine two."
    result = clean_content(content)
    assert "\n\n\n" not in result


def test_chunk_text_returns_non_empty_chunks():
    long_text = " ".join(["word"] * 2000)
    chunks = chunk_text(long_text)
    assert len(chunks) > 1
    assert all(len(c) > 0 for c in chunks)


def test_chunk_text_overlaps():
    # Each chunk should share some content with the next
    long_text = " ".join([f"word{i}" for i in range(2000)])
    chunks = chunk_text(long_text)
    # Last words of chunk 0 should appear at start of chunk 1
    last_words_of_first = chunks[0].split()[-20:]
    first_words_of_second = chunks[1].split()[:20]
    overlap = set(last_words_of_first) & set(first_words_of_second)
    assert len(overlap) > 0


def test_chunk_short_text_is_single_chunk():
    short = "This is a short note."
    chunks = chunk_text(short)
    assert len(chunks) == 1
    assert chunks[0] == short
