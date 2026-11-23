"""Handwritten digit reading for the marks boxes.

A small neural network (scikit-learn MLP) trained on the MNIST training set reads one digit per
box. Boxes are prepared the way MNIST digits were: ink only, white on black, fitted into 20 x 20
and centred by mass in 28 x 28. The model is trained once by `python -m scripts.train_digits`
and cached in models/digits.joblib (not committed).

MNIST's last 10,000 digits are never used for training: the sample generator draws its
"handwriting" from them, so accuracy on generated sheets is measured on unseen writing.
"""

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

from api import config

MODEL_PATH: Path = config.MODELS_DIR / "digits.joblib"
TRAIN_SIZE = 60_000                      # MNIST's standard split: 60k train, 10k test
BLANK_INK = 0.012                        # share of a box's pixels that must be ink to count as written


def load_mnist() -> tuple[np.ndarray, np.ndarray]:
    """MNIST as (images uint8 [70000, 28, 28], labels int [70000]); downloaded once by scikit-learn
    from OpenML into its data cache."""
    from sklearn.datasets import fetch_openml
    x, y = fetch_openml("mnist_784", version=1, as_frame=False, parser="liac-arff", return_X_y=True)
    return x.reshape(-1, 28, 28).astype(np.uint8), y.astype(int)


def train(path: Path = MODEL_PATH) -> float:
    """Train on the first 60k digits, save the model, and return accuracy on the last 10k."""
    import joblib
    from sklearn.neural_network import MLPClassifier

    images, labels = load_mnist()
    x = images.reshape(len(images), -1).astype(np.float32) / 255.0
    clf = MLPClassifier(hidden_layer_sizes=(256,), alpha=1e-4, batch_size=256, max_iter=30,
                        early_stopping=True, random_state=0)
    clf.fit(x[:TRAIN_SIZE], labels[:TRAIN_SIZE])
    accuracy = float(clf.score(x[TRAIN_SIZE:], labels[TRAIN_SIZE:]))
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(clf, path)
    model.cache_clear()
    return accuracy


@lru_cache(maxsize=1)
def model():
    import joblib
    if not MODEL_PATH.exists():
        raise RuntimeError("The digit model is missing; run: python -m scripts.train_digits")
    return joblib.load(MODEL_PATH)


def to_mnist(box: np.ndarray) -> np.ndarray | None:
    """A grayscale box (dark ink on light paper, uint8) as a 28 x 28 MNIST-style image, or None if
    the box is blank. A margin is cleared first so the printed box border does not count as ink."""
    h, w = box.shape
    m = max(2, round(min(h, w) * 0.12))
    inner = box[m:h - m, m:w - m]
    ink = 255 - inner.astype(np.int16)
    _, mask = cv2.threshold(ink.astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if ink.max() < 80:                                   # nothing darker than light grey
        return None
    # Keep connected strokes of a reasonable size; drop specks from scanning noise.
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = np.zeros_like(mask)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= max(6, mask.size * 0.002):
            keep[labels == i] = 255
    if keep.mean() / 255.0 < BLANK_INK:
        return None
    ys, xs = np.nonzero(keep)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    digit = np.where(keep[y0:y1, x0:x1] > 0, ink[y0:y1, x0:x1], 0).astype(np.float32)
    digit = digit / max(digit.max(), 1.0) * 255.0
    # Fit into 20 x 20, keeping the aspect ratio.
    dh, dw = digit.shape
    s = 20.0 / max(dh, dw)
    nh, nw = max(1, round(dh * s)), max(1, round(dw * s))
    digit = cv2.resize(digit, (nw, nh), interpolation=cv2.INTER_AREA)
    out = np.zeros((28, 28), np.float32)
    top, left = (28 - nh) // 2, (28 - nw) // 2
    out[top:top + nh, left:left + nw] = digit
    # Centre by mass, as MNIST was prepared.
    total = out.sum()
    if total > 0:
        cy = (out.sum(axis=1) * np.arange(28)).sum() / total
        cx = (out.sum(axis=0) * np.arange(28)).sum() / total
        shift = np.float32([[1, 0, 14 - cx], [0, 1, 14 - cy]])
        out = cv2.warpAffine(out, shift, (28, 28))
    return np.clip(out, 0, 255).astype(np.uint8)


def read(boxes: list[np.ndarray]) -> list[tuple[int | None, float]]:
    """(digit or None for blank, confidence 0-1) for each box."""
    images = [to_mnist(b) for b in boxes]
    written = [i for i, im in enumerate(images) if im is not None]
    out: list[tuple[int | None, float]] = [(None, 1.0)] * len(boxes)
    if written:
        x = np.stack([images[i].reshape(-1) for i in written]).astype(np.float32) / 255.0
        proba = model().predict_proba(x)
        classes = model().classes_
        for k, i in enumerate(written):
            j = int(proba[k].argmax())
            out[i] = (int(classes[j]), float(proba[k][j]))
    return out
