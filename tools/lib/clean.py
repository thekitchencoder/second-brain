import re
import yaml


def extract_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML front matter. Returns (metadata_dict, remaining_content)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    yaml_block = text[3:end].strip()
    content = text[end + 4:].lstrip("\n")
    try:
        meta = yaml.safe_load(yaml_block) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, content


# Characters used in box-drawing and ASCII art
_BOX_CHARS = set("─│┼╔╗╚╝╠╣╦╩╬═║┌┐└┘├┤┬┴")
_REPEATED_SYMBOL_RE = re.compile(r"^[+\-=_~*#|]{4,}\s*$")
_CODE_BLOCK_RE = re.compile(r"```(\w*)\n.*?```", re.DOTALL)
_TABLE_SEPARATOR_RE = re.compile(r"^\|[\s\-:]+\|[\s\-:|]*$")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def _is_ascii_art_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    box_count = sum(1 for c in stripped if c in _BOX_CHARS)
    if len(stripped) > 0 and box_count / len(stripped) > 0.5:
        return True
    if _REPEATED_SYMBOL_RE.match(stripped):
        return True
    return False


def _collapse_code_block(match: re.Match) -> str:
    lang = match.group(1).strip()
    return f"[code block: {lang}]" if lang else "[code block]"


# Both separator rows and data rows are simplified — table structure is intentionally lost for embedding
def _simplify_table_line(line: str) -> str:
    if _TABLE_SEPARATOR_RE.match(line.strip()):
        return ""
    if line.strip().startswith("|"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        return " ".join(c for c in cells if c)
    return line


def clean_content(content: str) -> str:
    """Clean document content for embedding. Strips noise, preserves prose."""
    # Collapse fenced code blocks first (before line-by-line processing)
    content = _CODE_BLOCK_RE.sub(_collapse_code_block, content)

    lines = content.splitlines()
    cleaned = []
    for line in lines:
        if _is_ascii_art_line(line):
            continue
        cleaned.append(_simplify_table_line(line))

    result = "\n".join(cleaned)
    result = _MULTI_BLANK_RE.sub("\n\n", result)
    return result.strip()


# ~4 chars per token; 400 tokens ≈ 1600 chars; 50-token overlap ≈ 200 chars
_CHUNK_SIZE = 1600
_CHUNK_OVERLAP = 200


def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks, splitting on paragraph boundaries."""
    if len(text) <= _CHUNK_SIZE:
        return [text]

    paragraphs = re.split(r"\n\n+", text)
    chunks = []
    current = []
    current_len = 0

    for para in paragraphs:
        # If a single paragraph is itself larger than the chunk size, split it
        # by words so it doesn't swallow the entire output into one chunk.
        if len(para) > _CHUNK_SIZE:
            sub_words = para.split(" ")
            sub_current: list[str] = []
            sub_len = 0
            for word in sub_words:
                word_len = len(word) + 1  # +1 for the space
                if sub_len + word_len > _CHUNK_SIZE and sub_current:
                    chunks.append(" ".join(sub_current))
                    # overlap: keep last N chars worth of words
                    overlap_words: list[str] = []
                    overlap_len = 0
                    for w in reversed(sub_current):
                        if overlap_len + len(w) + 1 < _CHUNK_OVERLAP:
                            overlap_words.insert(0, w)
                            overlap_len += len(w) + 1
                        else:
                            break
                    sub_current = overlap_words
                    sub_len = overlap_len
                sub_current.append(word)
                sub_len += word_len
            if sub_current:
                # treat the remainder as a normal paragraph for further merging
                para = " ".join(sub_current)
            else:
                continue

        para_len = len(para)
        if current_len + para_len > _CHUNK_SIZE and current:
            chunks.append("\n\n".join(current))
            # Carry the last paragraph forward as overlap
            current = [current[-1]] if current else []
            current_len = len(current[0]) if current else 0
        current.append(para)
        current_len += para_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks
