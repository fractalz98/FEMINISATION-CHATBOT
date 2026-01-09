from __future__ import annotations

import re
from typing import List, Tuple

MAX_WORDS = 8
MAX_CHARS = 60

SENTENCE_BOUNDARY = re.compile(r"([.!?])")


def _split_long_phrase(phrase: str) -> List[str]:
    words = phrase.split()
    chunks: List[str] = []
    current: List[str] = []
    for word in words:
        candidate = (" ".join(current + [word])).strip()
        if len(candidate) > MAX_CHARS or len(current) >= MAX_WORDS:
            if current:
                chunks.append(" ".join(current))
                current = [word]
            else:
                chunks.append(word[:MAX_CHARS])
                current = []
        else:
            current.append(word)
    if current:
        chunks.append(" ".join(current))
    return chunks


def _normalize_phrase(phrase: str) -> List[str]:
    cleaned = " ".join(phrase.strip().split())
    if not cleaned:
        return []
    if len(cleaned) <= MAX_CHARS and len(cleaned.split()) <= MAX_WORDS:
        return [cleaned]
    return _split_long_phrase(cleaned)


def extract_chunks(buffer: str) -> Tuple[List[str], str]:
    """
    Extract speakable chunks from the buffer.
    Returns (chunks, remainder).
    """
    chunks: List[str] = []
    working = buffer.replace(",", "\n")
    lines = working.split("\n")
    remainder = lines[-1]
    for line in lines[:-1]:
        line = line.strip()
        if not line:
            continue
        parts = []
        sentences = SENTENCE_BOUNDARY.split(line)
        if sentences:
            temp = ""
            for token in sentences:
                if SENTENCE_BOUNDARY.match(token):
                    temp += token
                    parts.append(temp)
                    temp = ""
                else:
                    if temp:
                        temp += token
                    else:
                        temp = token
            if temp:
                parts.append(temp)
        else:
            parts = [line]
        for part in parts:
            chunks.extend(_normalize_phrase(part))
    return chunks, remainder


def flush_buffer(buffer: str) -> List[str]:
    chunks, remainder = extract_chunks(buffer)
    if remainder.strip():
        chunks.extend(_normalize_phrase(remainder))
    return chunks
