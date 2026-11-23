"""Synthetic scanned PDFs for answer-sheet OCR (phase 7).

  python -m datagen.ocr_samples --assessment-id 42 [--database copo] [--seed 7] [--out samples/a42.pdf]

Page 1 is a printed question paper; each later page is one student's cover page (api/ocr/layout.py)
with marks "handwritten" from MNIST's held-out digits, which the digit model never saw. Pages are
rasterised and lightly rotated, shifted and noised like a scan, then saved as JPEG pages in an
image-only PDF.
An answer key (<out>.json) records every true value, for scripts/evaluate_ocr.py.

Everything is synthetic: no real question paper, answer sheet or student mark is used.
"""

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import fitz
import numpy as np

from api.ocr import layout

STEMS = [
    "Explain the three-schema architecture",
    "Normalise the relation to BCNF",
    "Write SQL for the given queries",
    "Draw the ER diagram for the case",
    "Compare B+ tree and hash indexes",
    "Explain two-phase locking",
    "Trace the recovery log",
    "Design triggers for the rules",
    "Discuss transaction isolation levels",
    "Write a recursive query",
]


@dataclass
class Question:
    q_no: str
    max_marks: int
    cos: list[int]
    bloom: int
    text: str = ""


@dataclass
class Paper:
    code: str
    title: str
    assessment: str
    max_marks: int
    questions: list[Question]


@dataclass
class Sheet:
    usn: str
    marks: dict[str, int]                 # q_no -> marks
    total: int = 0
    page: int = 0                         # filled in when the PDF is built


@dataclass
class Key:
    paper: Paper
    sheets: list[Sheet] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- drawing

def _render(page: fitz.Page) -> np.ndarray:
    pix = page.get_pixmap(dpi=layout.DPI, colorspace=fitz.csGRAY)
    return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()


def question_paper(doc: fitz.Document, paper: Paper) -> np.ndarray:
    page = doc.new_page(width=layout.PAGE_W, height=layout.PAGE_H)
    put = lambda x, y, t, s=10.5: page.insert_text((x, y), t, fontsize=s, fontname="helv")
    put(60, 70, "RV College of Engineering, Bengaluru", 13)
    put(60, 90, "Department of Information Science and Engineering")
    put(60, 115, f"{paper.code} {paper.title}")
    put(60, 133, f"{paper.assessment}    Max. marks: {paper.max_marks}")
    y = 170
    put(60, y, "Q.No"); put(100, y, "Question"); put(422, y, "Marks"); put(468, y, "CO"); put(535, y, "BL")
    page.draw_line((55, y + 6), (560, y + 6), width=0.6)
    for q in paper.questions:
        y += 24
        put(60, y, q.q_no)
        put(100, y, q.text)
        put(430, y, str(q.max_marks))
        put(468, y, ",".join(f"CO{c}" for c in q.cos))
        put(535, y, f"L{q.bloom}")
    return _render(page)


def cover_blank(doc: fitz.Document) -> np.ndarray:
    page = doc.new_page(width=layout.PAGE_W, height=layout.PAGE_H)
    put = lambda x, y, t, s=11: page.insert_text((x, y), t, fontsize=s, fontname="helv")
    for x, y in layout.FIDUCIALS.values():
        page.draw_rect(fitz.Rect(x, y, x + layout.FIDUCIAL, y + layout.FIDUCIAL), color=0, fill=0)
    put(70, 90, "RV College of Engineering - Answer booklet", 14)
    put(70, layout.USN_Y + 22, "USN    1RV")
    put(220, layout.USN_Y + 22, "branch")
    put(70, layout.MARKS_TOP - 18, "Marks (examiner)")
    boxes = [b for i in range(layout.MAX_QUESTIONS) for b in layout.mark_boxes(i)]
    for i in range(layout.MAX_QUESTIONS):
        x, y = layout.label_position(i)
        put(x, y, layout.question_label(i))
    put(70, layout.TOTAL_Y + 22, "Total")
    for b in [*layout.USN_YEAR, *layout.USN_ROLL, *boxes, *layout.TOTAL]:
        page.draw_rect(fitz.Rect(b.x, b.y, b.x + b.w, b.y + b.h), color=0, width=0.8)
    return _render(page)


def _write_digit(img: np.ndarray, box: layout.Box, digit: np.ndarray, rng: np.random.Generator) -> None:
    """Darken the box with an MNIST digit (white on black) scaled to the box, with a little jitter."""
    x0, y0, x1, y1 = box.px()
    bw, bh = x1 - x0, y1 - y0
    size = int(min(bw, bh) * rng.uniform(0.95, 1.15))
    d = cv2.resize(digit.astype(np.float32), (size, size), interpolation=cv2.INTER_LINEAR)
    cx = x0 + bw // 2 + int(rng.integers(-3, 4))
    cy = y0 + bh // 2 + int(rng.integers(-3, 4))
    top, left = cy - size // 2, cx - size // 2
    region = img[top:top + size, left:left + size].astype(np.float32)
    ink = d[:region.shape[0], :region.shape[1]] * rng.uniform(0.75, 0.95)
    img[top:top + size, left:left + size] = np.minimum(region, 255 - ink).astype(np.uint8)


def write_number(img, boxes, value, digits_by_label, rng, width, pad: str = " ") -> None:
    """Right-aligned: a mark of 7 goes in the units box. USN digits are zero-padded (pad="0")."""
    text = str(value).rjust(width, pad)
    for box, ch in zip(boxes, text):
        if ch != " ":
            pool = digits_by_label[int(ch)]
            _write_digit(img, box, pool[int(rng.integers(len(pool)))], rng)


def scan(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """A light imitation of a scanner: small rotation and shift, blur, grain."""
    h, w = img.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), float(rng.uniform(-1.0, 1.0)), float(rng.uniform(0.985, 1.015)))
    m[:, 2] += rng.uniform(-12, 12, size=2)
    out = cv2.warpAffine(img, m, (w, h), borderValue=255)
    out = cv2.GaussianBlur(out, (3, 3), 0)
    noise = rng.normal(0, 6, out.shape)
    return np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def build_pdf(key: Key, out: Path, seed: int = 7, digits: np.ndarray | None = None,
              labels: np.ndarray | None = None) -> Path:
    """Write the scanned PDF for `key` (and its answer key as JSON next to it)."""
    from api.ocr.digits import TRAIN_SIZE, load_mnist
    rng = np.random.default_rng(seed)
    if digits is None:
        digits, labels = load_mnist()
    held_out = digits[TRAIN_SIZE:], labels[TRAIN_SIZE:]
    by_label = {d: held_out[0][held_out[1] == d] for d in range(10)}

    scratch = fitz.open()
    pages = [scan(question_paper(scratch, key.paper), rng)]
    for sheet in key.sheets:
        img = cover_blank(scratch)
        write_number(img, layout.USN_YEAR, int(sheet.usn[3:5]), by_label, rng, 2, "0")
        write_number(img, layout.USN_ROLL, int(sheet.usn[7:10]), by_label, rng, 3, "0")
        for i, q in enumerate(key.paper.questions):
            write_number(img, layout.mark_boxes(i), sheet.marks[q.q_no], by_label, rng, 2)
        sheet.total = sum(sheet.marks.values())
        write_number(img, layout.TOTAL, sheet.total, by_label, rng, 3)
        sheet.page = len(pages) + 1
        pages.append(scan(img, rng))

    pdf = fitz.open()
    for img in pages:
        # JPEG, as scanners save: a noisy page as PNG is ~1.8 MB, as JPEG ~0.2 MB.
        ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        page = pdf.new_page(width=layout.PAGE_W, height=layout.PAGE_H)
        page.insert_image(page.rect, stream=jpg.tobytes())
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(out, deflate=True)
    out.with_suffix(".json").write_text(json.dumps(asdict(key), indent=1))
    return out


def random_key(paper: Paper, usns: list[str], rng: np.random.Generator, absent_share: float = 0.05) -> Key:
    """Marks for every enrolled USN; a few are absent and get no cover page."""
    key = Key(paper=paper)
    for usn in usns:
        if rng.random() < absent_share:
            key.absent.append(usn)
            continue
        key.sheets.append(Sheet(usn=usn, marks={q.q_no: int(rng.integers(0, q.max_marks + 1))
                                                for q in paper.questions}))
    rng.shuffle(key.sheets)                   # scanned in no particular order
    return key


# ---------------------------------------------------------------- from the database

def paper_from_db(conn, assessment_id: int, rng: np.random.Generator) -> tuple[Paper, list[str]]:
    a = conn.execute("""
        SELECT a.name, a.max_marks, c.code, c.title, a.offering_id
        FROM assessment a JOIN course_offering o USING (offering_id) JOIN course c USING (course_id)
        WHERE a.assessment_id = %s""", (assessment_id,)).fetchone()
    if not a:
        raise SystemExit(f"assessment {assessment_id} not found")
    rows = conn.execute("""
        SELECT q.q_no, q.max_marks, coalesce(q.bloom_level, 0) AS bloom,
               array_agg(co.co_number ORDER BY co.co_number) AS cos
        FROM assessment_question q
        JOIN question_co_map m USING (question_id) JOIN course_outcome co USING (co_id)
        WHERE q.assessment_id = %s GROUP BY q.question_id ORDER BY q.question_id""", (assessment_id,)).fetchall()
    if not rows or len(rows) > layout.MAX_QUESTIONS:
        raise SystemExit(f"assessment {assessment_id} needs 1 to {layout.MAX_QUESTIONS} tagged questions")
    questions = [Question(q_no=r["q_no"], max_marks=int(r["max_marks"]), cos=list(r["cos"]),
                          bloom=int(r["bloom"]) or int(rng.integers(1, 5)), text=STEMS[i % len(STEMS)])
                 for i, r in enumerate(rows)]
    usns = [r["usn"] for r in conn.execute(
        "SELECT usn FROM enrollment WHERE offering_id = %s ORDER BY usn", (a["offering_id"],))]
    return Paper(a["code"], a["title"], a["name"], int(a["max_marks"]), questions), usns


def main() -> None:
    import psycopg
    from psycopg.rows import dict_row

    from api import config

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--assessment-id", type=int, required=True)
    p.add_argument("--database", default=None)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    rng = np.random.default_rng(args.seed)
    with psycopg.connect(config.owner_dsn(args.database), row_factory=dict_row) as conn:
        paper, usns = paper_from_db(conn, args.assessment_id, rng)
    out = args.out or config.ROOT / "samples" / f"assessment-{args.assessment_id}.pdf"
    key = random_key(paper, usns, rng)
    build_pdf(key, out, seed=args.seed)
    print(f"wrote {out} ({len(key.sheets) + 1} pages, {len(key.absent)} absent) and {out.with_suffix('.json').name}")


if __name__ == "__main__":
    main()
