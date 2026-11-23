"""The synthetic answer-sheet cover page, shared by the sample generator and the reader.

Positions are PDF points on an A4 page (595 x 842, origin top left). Four filled squares at the
corners let the reader undo the small shift, rotation and scale of a scan before it looks inside
the boxes. The layout is a stand-in designed for this project; a college's real cover page can
replace it by changing these numbers.

    ■                                                    ■
       RV College of Engineering · Answer booklet
       USN  1RV [y][y]  branch  [r][r][r]
       Marks (examiner)
       Q1  [t][u]        Q6  [t][u]
       ...               ...
       Q5  [t][u]        Q10 [t][u]
       Total [h][t][u]
    ■                                                    ■

Each mark is written as two digits, tens and units (a single-digit mark goes in the units box).
Half marks are not supported.
"""

from dataclasses import dataclass

PAGE_W, PAGE_H = 595.0, 842.0
DPI = 200
SCALE = DPI / 72.0                       # points to pixels at the rendering resolution

# Fiducial squares: top-left corner and size, in points.
FIDUCIAL = 22.0
FIDUCIALS = {
    "tl": (28.0, 28.0),
    "tr": (PAGE_W - 28.0 - FIDUCIAL, 28.0),
    "bl": (28.0, PAGE_H - 28.0 - FIDUCIAL),
    "br": (PAGE_W - 28.0 - FIDUCIAL, PAGE_H - 28.0 - FIDUCIAL),
}

BOX_W, BOX_H = 26.0, 32.0                # one handwritten digit
BOX_GAP = 4.0
MAX_QUESTIONS = 10                       # Q1..Q10 on the cover page


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    w: float = BOX_W
    h: float = BOX_H

    def px(self) -> tuple[int, int, int, int]:
        """(x0, y0, x1, y1) in pixels at DPI."""
        return (round(self.x * SCALE), round(self.y * SCALE),
                round((self.x + self.w) * SCALE), round((self.y + self.h) * SCALE))


def _row(x: float, y: float, n: int) -> list[Box]:
    return [Box(x + i * (BOX_W + BOX_GAP), y) for i in range(n)]


USN_Y = 150.0
USN_YEAR = _row(150.0, USN_Y, 2)        # after the printed "1RV"
USN_ROLL = _row(300.0, USN_Y, 3)        # after the printed "branch" gap

MARKS_TOP = 260.0
MARKS_ROW_H = 52.0
_COLUMNS = ((70.0, 130.0), (320.0, 380.0))   # (label x, first box x) for Q1-Q5 and Q6-Q10


def question_label(i: int) -> str:
    return f"Q{i + 1}"


def mark_boxes(i: int) -> list[Box]:
    """Tens and units boxes of question i (0-based)."""
    label_x, box_x = _COLUMNS[i // 5]
    return _row(box_x, MARKS_TOP + (i % 5) * MARKS_ROW_H, 2)


def label_position(i: int) -> tuple[float, float]:
    label_x, _ = _COLUMNS[i // 5]
    return label_x, MARKS_TOP + (i % 5) * MARKS_ROW_H + 22.0


TOTAL_Y = MARKS_TOP + 5 * MARKS_ROW_H + 24.0
TOTAL = _row(130.0, TOTAL_Y, 3)          # hundreds, tens, units


def canvas_px() -> tuple[int, int]:
    """Width and height of a page rendered at DPI."""
    return round(PAGE_W * SCALE), round(PAGE_H * SCALE)


def fiducial_centres_px() -> dict[str, tuple[float, float]]:
    return {k: ((x + FIDUCIAL / 2) * SCALE, (y + FIDUCIAL / 2) * SCALE) for k, (x, y) in FIDUCIALS.items()}
