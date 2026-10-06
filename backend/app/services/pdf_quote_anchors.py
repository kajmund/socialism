"""Map an exact original quote to word coordinates in visual PDF reading order."""

import pdfplumber


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _matching_words(words: list[dict], quote: str, *, first: bool = False) -> list[dict]:
    exact = _normalized(quote).split()
    if not exact:
        return []
    parts = [(index, value) for index, word in enumerate(words)
             for value in _normalized(str(word.get("text") or "")).split()]
    original = [value for _index, value in parts]
    matches = [index for index in range(len(parts) - len(exact) + 1)
               if original[index:index + len(exact)] == exact]
    if not matches or (not first and len(matches) != 1):
        return []
    start = matches[0]
    return words[parts[start][0]:parts[start + len(exact) - 1][0] + 1]


def _line_rects(page: pdfplumber.page.Page, words: list[dict]) -> list[dict[str, float]]:
    lines: list[list[dict]] = []
    for word in words:
        top = float(word["top"])
        line = next((group for group in lines if abs(float(group[0]["top"]) - top) <= 3.0), None)
        if line is None:
            line = []
            lines.append(line)
        line.append(word)
    rects = []
    for line in lines:
        x0 = min(float(word["x0"]) for word in line)
        x1 = max(float(word["x1"]) for word in line)
        top = min(float(word["top"]) for word in line)
        bottom = max(float(word["bottom"]) for word in line)
        left, right = _clipped_span(x0, x1, float(page.width))
        upper, lower = _clipped_span(top, bottom, float(page.height))
        if left < right and upper < lower:
            rects.append({"x": left, "y": upper, "width": right - left, "height": lower - upper})
    return rects


def _clipped_span(start: float, end: float, extent: float) -> tuple[float, float]:
    return max(0.0, min(1.0, start / extent)), max(0.0, min(1.0, end / extent))


def quote_rects(pdf: pdfplumber.PDF, page_number: int, quote: str) -> list[dict[str, float]]:
    if page_number < 1 or page_number > len(pdf.pages):
        return []
    page = pdf.pages[page_number - 1]
    if not page.width or not page.height:
        return []
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    return _line_rects(page, _matching_words(words, quote))


def first_quote_page(pdf: pdfplumber.PDF, quote: str) -> tuple[int, list[dict[str, float]]] | None:
    """The first visual occurrence, including a phrase that is repeated."""
    for number, page in enumerate(pdf.pages, start=1):
        if not page.width or not page.height:
            continue
        words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
        rects = _line_rects(page, _matching_words(words, quote, first=True))
        if rects:
            return number, rects
    return None
