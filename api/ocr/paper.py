"""Read the printed question paper (page 1) with Tesseract.

Each question line reads `Q<n>  <question text>  <max marks>  CO<a>[,CO<b>]  L<bloom>`, as in the
synthetic paper (datagen/ocr_samples.py). The last three fields are short codes in fixed places,
so they are taken by position and repaired for the usual OCR confusions (i, l, I and | for 1, O for
0, a doubled C), while the question text is kept as read. Lines that start like a question but do
not parse are returned as warnings, so the teacher sees what was skipped.
"""

import re

import cv2
import numpy as np
import pytesseract

from api import config

QUESTION = re.compile(
    r"^\s*(?P<q>Q\S{1,3})\s+(?P<text>.+?)\s+(?P<max>[\dOoIl|]{1,2})\s+"
    r"(?P<cos>\S+(?:\s*[,/&;]\s*\S+)*)\s+(?P<bl>(?:[Ll|]\s?)?[1-6Iil|])\s*$")   # the L is sometimes lost
STARTS_LIKE_QUESTION = re.compile(r"^\s*Q\S?\d", re.I)
MAX_MARKS = re.compile(r"max\.?\s*marks\s*[:\-]?\s*(\d{1,3})", re.I)
CONFUSED = str.maketrans({"I": "1", "i": "1", "L": "1", "l": "1", "|": "1", "!": "1",
                          "O": "0", "o": "0", "S": "5", "s": "5", "Z": "2", "z": "2", "B": "8"})


def _number(token: str) -> int | None:
    digits = re.sub(r"\D", "", token.translate(CONFUSED))
    return int(digits) if digits else None


def _co_numbers(field: str) -> list[int] | None:
    """'CO1,CO2', 'Cco2', 'C02', 'coli' -> CO numbers. Drops the C and O of the prefix, then takes
    the first digit 1-9 (CO numbers are single digits and never 0)."""
    out = []
    for part in re.split(r"[,/&;]", field):
        part = part.strip().upper().lstrip("C").lstrip("O0")
        digit = next((ch for ch in part.translate(CONFUSED) if ch in "123456789"), None)
        if digit is None:
            return None
        out.append(int(digit))
    return out or None


def parse(text: str) -> dict:
    questions, warnings = [], []
    paper_max = None
    for raw in text.splitlines():
        line = raw.replace("—", "-").strip()
        if not line:
            continue
        if paper_max is None and (m := MAX_MARKS.search(line)):
            paper_max = int(m.group(1))
        m = QUESTION.match(line)
        q_no = _number(m["q"][1:]) if m else None
        max_marks = _number(m["max"]) if m else None
        cos = _co_numbers(m["cos"]) if m else None
        bloom = _number(m["bl"][-1]) if m else None
        if m and q_no and max_marks and cos and bloom and 1 <= bloom <= 6:
            questions.append({"q_no": f"Q{q_no}", "text": m["text"].strip(), "max_marks": max_marks,
                              "cos": cos, "bloom": bloom})
        elif STARTS_LIKE_QUESTION.match(line):
            warnings.append(f"Could not read the question line: “{line}”")
    seen, unique = set(), []
    for q in questions:
        if q["q_no"] in seen:
            warnings.append(f"{q['q_no']} appears more than once; the first is kept")
            continue
        seen.add(q["q_no"])
        unique.append(q)
    return {"questions": unique, "paper_max": paper_max, "warnings": warnings}


def prepare(page: np.ndarray) -> np.ndarray:
    """Enlarge to about 300 dpi, remove scanner grain and binarise: Tesseract reads small print
    much better that way."""
    big = cv2.resize(page, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    big = cv2.medianBlur(big, 3)
    _, bw = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return bw


def read(page: np.ndarray) -> dict:
    """Parse a grayscale page image."""
    pytesseract.pytesseract.tesseract_cmd = config.tesseract_cmd()
    text = pytesseract.image_to_string(prepare(page), config="--psm 6")
    result = parse(text)
    result["text"] = text
    return result
