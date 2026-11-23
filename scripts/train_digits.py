"""Train the handwritten-digit model used by answer-sheet OCR.

  python -m scripts.train_digits

Downloads MNIST once (about 15 MB, from OpenML, cached by scikit-learn), trains on the first
60,000 digits and saves models/digits.joblib. Prints accuracy on the 10,000 held-out digits.
Takes a few minutes on a laptop CPU.
"""

from api.ocr import digits


def main() -> None:
    accuracy = digits.train()
    print(f"saved {digits.MODEL_PATH} - accuracy on 10,000 held-out MNIST digits: {accuracy:.2%}")


if __name__ == "__main__":
    main()
