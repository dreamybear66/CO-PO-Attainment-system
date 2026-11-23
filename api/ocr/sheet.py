"""Read one answer-sheet cover page: the USN digits, each question's mark and the total.

The four corner squares are found first and the page is warped back onto the layout, so every box
can be cut out by its known position (api/ocr/layout.py) even from a slightly skewed scan.
"""

import base64

import cv2
import numpy as np

from api.ocr import digits, layout


def find_corners(gray: np.ndarray) -> dict[str, tuple[float, float]] | None:
    """Centres of the four corner squares, or None if any is missing."""
    h, w = gray.shape
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    side = layout.FIDUCIAL * layout.SCALE * (w / layout.canvas_px()[0])
    found = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cv2.contourArea(c)
        if not (0.6 * side <= cw <= 1.5 * side and 0.6 * side <= ch <= 1.5 * side):
            continue
        if area < 0.8 * cw * ch:                     # filled, not an empty box outline
            continue
        found.append((x + cw / 2, y + ch / 2))
    corners = {}
    for name, (tx, ty) in {"tl": (0, 0), "tr": (w, 0), "bl": (0, h), "br": (w, h)}.items():
        near = [p for p in found if abs(p[0] - tx) < w * 0.25 and abs(p[1] - ty) < h * 0.2]
        if not near:
            return None
        corners[name] = min(near, key=lambda p: (p[0] - tx) ** 2 + (p[1] - ty) ** 2)
    return corners


def align(gray: np.ndarray) -> np.ndarray | None:
    corners = find_corners(gray)
    if corners is None:
        return None
    target = layout.fiducial_centres_px()
    order = ("tl", "tr", "bl", "br")
    m = cv2.getPerspectiveTransform(np.float32([corners[k] for k in order]),
                                    np.float32([target[k] for k in order]))
    return cv2.warpPerspective(gray, m, layout.canvas_px(), borderValue=255)


def _crop(page: np.ndarray, boxes: list[layout.Box], pad: int = 6) -> np.ndarray:
    x0, y0, _, _ = boxes[0].px()
    _, _, x1, y1 = boxes[-1].px()
    return page[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]


def png_data_url(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def boxes_probabilities(page: np.ndarray, boxes: list[layout.Box]) -> dict:
    """Digit probabilities of each box (None = blank) and a picture of the boxes for review."""
    cells = [page[y0:y1, x0:x1] for x0, y0, x1, y1 in (b.px() for b in boxes)]
    return {"probas": digits.probabilities(cells), "image": png_data_url(_crop(page, boxes))}


def read(gray: np.ndarray, n_questions: int) -> dict:
    """What is written on one cover page, undecided: the caller picks values with what it knows
    (question maxima, enrolled USNs). `aligned` False means the corner squares were not found."""
    page = align(gray)
    if page is None:
        return {"aligned": False, "image": png_data_url(cv2.resize(gray, None, fx=0.25, fy=0.25))}
    usn_boxes = [*layout.USN_YEAR, *layout.USN_ROLL]
    x0, y0 = layout.USN_YEAR[0].px()[:2]
    x1, y1 = layout.USN_ROLL[-1].px()[2:]
    usn = boxes_probabilities(page, usn_boxes)
    usn["image"] = png_data_url(page[y0 - 8:y1 + 8, x0 - 130:x1 + 8])   # include the printed 1RV
    return {
        "aligned": True,
        "usn": usn,
        "marks": [boxes_probabilities(page, layout.mark_boxes(i))
                  for i in range(min(n_questions, layout.MAX_QUESTIONS))],
        "total": boxes_probabilities(page, layout.TOTAL),
    }
