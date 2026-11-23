"""Answer-sheet OCR (phase 7, PRD FR-3.7 to FR-3.9).

One PDF per assessment: page 1 is the printed question paper, every later page is one student's
answer-sheet cover page with the examiner's handwritten per-question marks. Everything runs
locally (Tesseract for printed text, a digit model trained on MNIST for handwriting) and only
suggests values: nothing is saved until the teacher confirms it on the review screen.
"""
