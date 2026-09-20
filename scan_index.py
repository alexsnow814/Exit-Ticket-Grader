"""Persistent, page-level OCR index for the grader's scan folders.

The sheet stores header OCR, not grades or PDF content. File versions make an
unchanged PDF reusable even when another PDF is added to the same folder.
"""

from __future__ import annotations

from dataclasses import dataclass


INDEX_SHEET = "scan_index"
INDEX_HEADERS = [
    "exit_ticket", "pdf_name", "file_id", "modified_time", "file_size",
    "page_number", "page_count", "header_text",
]


@dataclass(frozen=True)
class IndexedPage:
    page_index: int
    page_count: int
    header_text: str


def parse_index(values: list[list[str]]) -> dict[tuple[str, str, str], dict[int, IndexedPage]]:
    """Read the index, tolerating duplicate/partial writes but not bad headers."""
    if not values:
        return {}
    if values[0][:len(INDEX_HEADERS)] != INDEX_HEADERS:
        raise ValueError("scan_index has unexpected column headings")
    result: dict[tuple[str, str, str], dict[int, IndexedPage]] = {}
    for row in values[1:]:
        padded = [*row, *([""] * max(0, len(INDEX_HEADERS) - len(row)))]
        _, _, file_id, modified_time, file_size, page_number, page_count, header_text = padded[:8]
        try:
            page_index = int(page_number) - 1
            count = int(page_count)
        except (TypeError, ValueError):
            continue
        if not file_id or count < 1 or not 0 <= page_index < count:
            continue
        version = (file_id, modified_time, file_size)
        result.setdefault(version, {})[page_index] = IndexedPage(
            page_index, count, header_text
        )
    return result


def indexed_prefix(
    index: dict[tuple[str, str, str], dict[int, IndexedPage]],
    version: tuple[str, str, str],
) -> list[IndexedPage]:
    """Only contiguous pages are usable; a partial write resumes safely."""
    by_page = index.get(version, {})
    pages = []
    while len(pages) in by_page:
        pages.append(by_page[len(pages)])
    return pages


def file_is_complete(
    index: dict[tuple[str, str, str], dict[int, IndexedPage]],
    version: tuple[str, str, str],
) -> bool:
    pages = indexed_prefix(index, version)
    return bool(pages) and len(pages) == pages[0].page_count and all(
        page.page_count == pages[0].page_count for page in pages
    )


def rows_for_pages(
    ticket_name: str,
    pdf_name: str,
    version: tuple[str, str, str],
    page_count: int,
    matches,
) -> list[list[object]]:
    file_id, modified_time, file_size = version
    return [
        [ticket_name, pdf_name, file_id, modified_time, file_size,
         match.page_index + 1, page_count, match.ocr_text]
        for match in matches
    ]
