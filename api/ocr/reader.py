"""Read a whole answer-sheet PDF: page 1 is the question paper, every later page a cover page.

Pure reading, no database: the API matches what was read against the assessment, its course
and its enrolled students (api/routers/ocr.py).
"""

import fitz
import numpy as np

from api.ocr import digits, layout, paper, sheet

MAX_PAGES = 400
DEFAULT_REVIEW_CONFIDENCE = 0.90       # attainment_config.ocr_review_confidence's default, for tools without a database


class OcrError(ValueError):
    """The file cannot be read at all (not a PDF, empty, too long)."""


def pages(data: bytes) -> list[np.ndarray]:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:                      # PyMuPDF raises several types for bad input
        raise OcrError("The file is not a readable PDF") from exc
    if doc.page_count < 2:
        raise OcrError("The PDF needs the question paper on page 1 and at least one cover page after it")
    if doc.page_count > MAX_PAGES:
        raise OcrError(f"The PDF has {doc.page_count} pages; at most {MAX_PAGES} are read at once")
    out = []
    for page in doc:
        pix = page.get_pixmap(dpi=layout.DPI, colorspace=fitz.csGRAY)
        out.append(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy())
    return out


def read_pdf(data: bytes, n_questions: int | None = None) -> dict:
    """The question paper and, undecided, what is written on every cover page. n_questions is how
    many mark rows to read; by default as many as the paper lists."""
    images = pages(data)
    qp = paper.read(images[0])
    qp.pop("text", None)
    n = n_questions or max(len(qp["questions"]), 1)
    sheets = []
    for number, img in enumerate(images[1:], start=2):
        s = sheet.read(img, n)
        s["page"] = number
        sheets.append(s)
    return {"paper": qp, "sheets": sheets}


def cover_row(q: dict) -> int | None:
    """Cover-page row of a question: Q1 is row 0. None for a number the cover page has no row for."""
    n = q["q_no"][1:]
    return int(n) - 1 if n.isdigit() and 1 <= int(n) <= layout.MAX_QUESTIONS else None


def _assign_usns(sheets: list[dict], candidates: list[str]) -> dict[int, tuple[str, float]]:
    """page -> (USN, confidence). Every enrolled USN goes to at most one sheet: the pairing with the
    highest total likelihood (Hungarian algorithm), so one misread digit does not give two sheets
    the same student. Confidence is the chosen USN's share of that sheet's probability, so a sheet
    pushed away from its own best reading comes out low and is checked."""
    from scipy.optimize import linear_sum_assignment

    if not sheets or not candidates:
        return {}
    texts = [u[3:5] + u[7:10] for u in candidates]
    scores = np.array([[digits.log_likelihood(s["usn"]["probas"], t) for t in texts] for s in sheets])
    rows, cols = linear_sum_assignment(-scores)
    out = {}
    for r, c in zip(rows, cols):
        row = np.exp(scores[r] - scores[r].max())
        out[sheets[r]["page"]] = (candidates[c], float(row[c] / row.sum()))
    return out


def review(raw: dict, questions: list[dict], enrolled: list[str], threshold: float) -> dict:
    """Pick a value for everything on the cover pages and say what the teacher should check.

    questions: [{q_no, max_marks}]. Each is read from its own cover-page row by number (Q3 from row 3),
    so a question line page 1 could not read never shifts the others; questions beyond the cover
    page's rows are left out. enrolled: the offering's USNs.
    Each USN is chosen among the enrolled ones and each mark among 0..its maximum, by how well
    they explain the digit probabilities; `confidence` is that choice's share of the probability.
    A value below `threshold` is marked `check`.
    """
    candidates = [u for u in enrolled if len(u) == 10 and u[3:5].isdigit() and u[7:10].isdigit()]
    usns = _assign_usns([s for s in raw["sheets"] if s["aligned"]], candidates)
    maxima = [int(q["max_marks"]) for q in questions]
    out, by_usn = [], {}
    for s in raw["sheets"]:
        item = {"page": s["page"], "problems": []}
        if not s["aligned"]:
            # One empty, flagged input per question, so the teacher can type the marks or skip the page.
            item.update(usn=None, usn_confidence=0.0, usn_image=s["image"], total=None, check=True,
                        marks=[{"q_no": q["q_no"], "value": None, "blank": True, "confidence": 0.0,
                                "check": True, "image": None} for q in questions if cover_row(q) is not None])
            item["problems"].append("The corner squares were not found; type this sheet's marks or skip the page")
            out.append(item)
            continue
        usn, usn_conf = usns.get(s["page"], (None, 0.0))
        marks = []
        for q in questions:
            row = cover_row(q)
            if row is None or row >= len(s["marks"]):
                continue
            m = s["marks"][row]
            value, conf = digits.best_number(m["probas"], int(q["max_marks"]))
            marks.append({"q_no": q["q_no"], "value": 0 if value is None else value,
                          "blank": value is None, "confidence": round(conf, 3),
                          "check": conf < threshold, "image": m["image"]})
        total, total_conf = digits.best_number(s["total"]["probas"], max(sum(maxima), 1))
        summed = sum(m["value"] for m in marks)
        if total is not None and total != summed:
            item["problems"].append(f"The total written on the sheet ({total}) is not the sum of the marks ({summed})")
        if usn_conf < threshold:
            item["problems"].append("The USN is hard to read; check it")
        item.update(usn=usn, usn_confidence=round(usn_conf, 3), usn_image=s["usn"]["image"],
                    marks=marks, total={"value": total, "confidence": round(total_conf, 3),
                                        "image": s["total"]["image"]})
        if usn:
            by_usn.setdefault(usn, []).append(item)
        out.append(item)
    for usn, items in by_usn.items():
        if len(items) > 1:
            pages_ = ", ".join(str(it["page"]) for it in items)
            for it in items:
                it["problems"].append(f"{usn} is read on more than one page ({pages_})")
    for item in out:
        item["check"] = bool(item["problems"]) or any(m["check"] for m in item["marks"])
    absent = sorted(set(enrolled) - set(by_usn))
    return {"sheets": out, "absent": absent}
