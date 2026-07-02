#!/bin/bash
# Step 1 of the pipeline: render the PDF pages to 300 dpi grayscale images and OCR them
# with Tesseract. Outputs:
#   work/ocr-images/p<NNN>.png   (regenerable page images, git-ignored)
#   artifacts/ocr/p<NNN>.txt      (first-pass OCR text; the scaffold shown to the proofreading agents)
# Requires: python3 with PyMuPDF (fitz), and tesseract on PATH.
set -e
ROOT="${PT_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PDF="$ROOT/Murphy, Thomas - Pastoral Theology.pdf"
IMG="$ROOT/work/ocr-images"
TXT="$ROOT/artifacts/ocr"
mkdir -p "$IMG" "$TXT"

# 1. Render 300 dpi grayscale images (front matter 4-7, body+index 14-510)
PDF="$PDF" IMG="$IMG" python3 - <<'PY'
import fitz, os
doc = fitz.open(os.environ["PDF"])
img = os.environ["IMG"]
mat = fitz.Matrix(300/72, 300/72)
for i in list(range(4, 8)) + list(range(14, 511)):
    out = f"{img}/p{i:03d}.png"
    if os.path.exists(out):
        continue
    doc[i].get_pixmap(matrix=mat, colorspace=fitz.csGRAY).save(out)
print("render done")
PY

# 2. Tesseract each page (LSTM, single-uniform-block)
n=0
for i in $(seq -w 4 7) $(seq -w 14 510); do
  ii=$(printf "%03d" $((10#$i)))
  if [ -f "$IMG/p$ii.png" ] && [ ! -f "$TXT/p$ii.txt" ]; then
    tesseract "$IMG/p$ii.png" "$TXT/p$ii" --psm 6 --oem 1 -l eng 2>/dev/null
    n=$((n+1))
  fi
done
echo "ocr done: $n new pages | total: $(ls "$TXT" | wc -l | tr -d ' ')"
