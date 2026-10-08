"""Page-number helpers shared by all modules. Page numbers shown to the user are
1-based; internally pages are 0-based."""
from __future__ import annotations

import re


def parse_page_range(text: str, page_count: int, keep_order: bool = False) -> list[int]:
    """'1-3, 7, 10-' -> [0, 1, 2, 6, 9, ...] (0-based, sorted, unique).

    With `keep_order`, pages stay in the order typed ('3, 1' -> [2, 0]) and repeats
    are kept. Also accepts 'all', 'odd', 'even', 'last'. Raises ValueError with a
    clear message.
    """
    pages: list[int] = []
    text = (text or "").strip().lower()
    if not text:
        raise ValueError("Enter the pages, for example 1-5, 8, 10-12")
    if text == "all":
        return list(range(page_count))
    if text == "odd":
        return list(range(0, page_count, 2))
    if text == "even":
        return list(range(1, page_count, 2))
    for part in re.split(r"[,;]\s*", text):
        part = part.strip().replace("last", str(page_count))
        if not part:
            continue
        m = re.fullmatch(r"(\d*)\s*-\s*(\d*)", part)
        if m:
            a = int(m.group(1)) if m.group(1) else 1
            b = int(m.group(2)) if m.group(2) else page_count
        elif part.isdigit():
            a = b = int(part)
        else:
            raise ValueError(f"'{part}' is not a page number or range")
        if a < 1 or b > page_count or a > b:
            raise ValueError(f"'{part}' is outside 1-{page_count}")
        pages.extend(range(a - 1, b))
    if not pages:
        raise ValueError("No pages selected")
    return pages if keep_order else sorted(set(pages))


def parse_range_groups(text: str, page_count: int) -> list[list[int]]:
    """'1-3; 4-10; 11-' -> [[0,1,2],[3..9],[10..]]: each comma/semicolon part is one group
    (order kept). Used by Split."""
    groups = []
    for part in re.split(r"[,;]\s*", (text or "").strip()):
        if part.strip():
            groups.append(parse_page_range(part, page_count))
    if not groups:
        raise ValueError("Enter at least one range, for example 1-3, 4-10")
    return groups


def describe_pages(pages: list[int], limit: int = 12) -> str:
    """[0,1,2,5] -> '1-3, 6'"""
    pages = sorted(set(pages))
    if not pages:
        return "none"
    ranges = []
    start = prev = pages[0]
    for p in pages[1:] + [None]:
        if p is not None and p == prev + 1:
            prev = p
            continue
        ranges.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
        if p is not None:
            start = prev = p
    text = ", ".join(ranges[:limit])
    return text + (", ..." if len(ranges) > limit else "")
