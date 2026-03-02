import re
from datetime import datetime

from bs4 import BeautifulSoup


def strip_html(html_content: str) -> str:
    """Strip HTML tags and return plain text."""
    soup = BeautifulSoup(html_content, "html.parser")
    return soup.get_text()


def extract_amount(text: str, pattern: str) -> str | None:
    """
    Search text for the amount pattern and return group(1), or None if no match.
    Pattern must have exactly one capturing group containing the numeric amount.
    """
    match = re.search(pattern, text)
    if match:
        return match.group(1)
    return None


def extract_due_date(text: str, pattern: str) -> str | None:
    """
    Search text for the due date pattern and return the matched date string.
    If the pattern has multiple capturing groups (e.g. month/day/year split),
    all groups are joined with a single space.
    Returns None if no match.
    """
    match = re.search(pattern, text)
    if not match:
        return None
    groups = match.groups()
    if len(groups) == 1:
        return groups[0]
    return " ".join(g for g in groups if g)


def normalize_date(raw_date: str, input_fmt, output_fmt: str) -> str | None:
    """
    Parse raw_date using input_fmt and reformat it using output_fmt.
    input_fmt may be a single format string or a list of format strings to try
    in order. Returns None if no format matches.

    Example:
        normalize_date("March 15, 2025", "%B %d, %Y", "%m/%d/%y") -> "03/15/25"
        normalize_date("Mar 15, 2025", ["%B %d, %Y", "%b %d, %Y"], "%m/%d/%y") -> "03/15/25"
    """
    formats = [input_fmt] if isinstance(input_fmt, str) else input_fmt
    for fmt in formats:
        try:
            date_obj = datetime.strptime(raw_date.strip(), fmt)
            return date_obj.strftime(output_fmt)
        except ValueError:
            continue
    return None
