# Pastoral Theology (Thomas Murphy, 1877) — reflowable EPUB edition

This repository holds a clean, reflowable **EPUB** edition of Thomas Murphy's
*Pastoral Theology: The Pastor in the Various Duties of His Office* (Presbyterian
Board of Publication, Philadelphia, 1877), reconstructed from the public-domain
scan — together with the **complete pipeline and intermediate artifacts** so the
edition can be rebuilt or audited.

The book is in the public domain (published 1877; author Thomas Murphy, 1823–1900).

- **Output:** [`Pastoral Theology - Thomas Murphy.epub`](./Pastoral%20Theology%20-%20Thomas%20Murphy.epub)
- **Source PDF:** [`Murphy, Thomas - Pastoral Theology.pdf`](./Murphy,%20Thomas%20-%20Pastoral%20Theology.pdf) — the scan distributed by
  [Log College Press](http://library.logcollegepress.com/Murphy%2C+Thomas%2C+Pastoral+Theology+A.pdf)
  (a copy held by Princeton Theological Seminary, archived by the Internet Archive as `pastoraltheology00murp`).

---

## How it was made (and why)

The source is a **scanned facsimile**: page images with an unreliable, error-filled
embedded OCR layer. The goal was clean, reflowable text with formatting preserved.

The obvious approach — have a language model transcribe each page image — **does not
work**: Anthropic's models decline to reproduce book-length text verbatim, and a hard
API output filter blocks it (verified: even a single full page from an image is blocked,
and ~83 % of full-page "corrections" were blocked). Chunking smaller to evade that filter
would be circumventing a safety control, so it was not done.

The working method keeps the language model **out of the text-generation loop** and uses
it only as an image-grounded **proofreader** of machine OCR:

```
 PDF ──▶ [1] render + Tesseract OCR ──▶ [2] per-page AI proofreading deltas ──▶
     ──▶ [3] geometry + delta reconstruction ──▶ [4] assemble EPUB
```

1. **Render + OCR** (`tools/run_ocr.sh`). Each page is rendered to a 300 dpi grayscale
   image and OCR'd with **Tesseract 4 (LSTM)** → `artifacts/ocr/`.
2. **Per-page AI proofreading** (`tools/wf_delta.js`). One **Claude Sonnet** agent per page,
   at *medium* reasoning effort, reads the page **image** alongside the OCR text and emits a
   small JSON *delta* — corrections, heading texts + levels, italic words, and lines to drop
   (running heads / page numbers). It outputs fixes, **not** the book text, so it passes the
   content filter. → `artifacts/deltas/`.
3. **Reconstruction** (`tools/ocr_reconstruct.py`). Tesseract's word-coordinate layout (TSV)
   is used to rebuild paragraphs, indents, headings, and chapter structure; the delta is
   applied on top (fixes, headings, italics, drops). → `artifacts/sections/`.
4. **Assembly** (`tools/assemble.py`). Sections are stitched (paragraphs merged across page
   breaks), front/back matter and a generated table of contents are added, and everything is
   packaged into a valid EPUB 3.

**Models used:** orchestration and all pipeline/assembly code were driven by **Claude Opus
4.8** under **Claude Code**; the per-page proofreading agents were **Claude Sonnet** at
*medium* effort. OCR is **Tesseract 4.1.1**. (This is documented in the book's own
*About This Edition* page as well.)

---

## Repository layout

```
Pastoral Theology - Thomas Murphy.epub   Final e-book (the deliverable)
Murphy, Thomas - Pastoral Theology.pdf   Source scan (input)
cover.jpg                                Designed cover art for this edition
assets/
  original-title-page.png                Facsimile of the original 1877 title page (used in the EPUB)
tools/
  run_ocr.sh          Step 1: render pages + Tesseract OCR
  wf_delta.js         Step 2: Claude Code Workflow — per-page AI proofreading deltas
  ocr_reconstruct.py  Step 3: rebuild per-page HTML from OCR geometry + deltas
  assemble.py         Step 4: assemble the EPUB
artifacts/
  ocr/        p<NNN>.txt        Tesseract OCR text, one file per page  (input to step 2)
  deltas/     delta_p<NNN>.json Per-page AI proofreading metadata       (output of step 2)
  sections/   sec_p<NNN>.html   Reconstructed page fragments            (output of step 3)
  overrides/  sec_p<NNN>.html   Hand-authored fragments for pages the automated pipeline
                                cannot produce (e.g. the chronological table on p. 119 /
                                index 120). When present, step 3 uses them verbatim.
work/                            Regenerable images + build tree (git-ignored)
```

`<NNN>` is the **0-based PDF page index**. Structure: front matter — title page `2`,
copyright `3`, preface `4–7`, printed contents `8–13`; **body `14–501`** (12 chapters, openers
at indices 14, 38, 92, 152, 224, 274, 327, 361, 428, 451, 472, 492); **index `502–510`**.
(The chapter map lives in `tools/ocr_reconstruct.py` and `tools/assemble.py`.)

### The `deltas/` format

Each `delta_p<NNN>.json` is the AI proofreader's output for one page:

```json
{
  "drop":     ["506 INDEX.", "39"],                 // exact lines to remove (running head, page no.)
  "fixes":    [{"wrong": "saered", "right": "sacred"}],  // OCR corrections (find/replace)
  "headings": [{"text": "History of Pastoral Theology", "level": "h2"}],
  "italics":  ["Manifestly, the word of God"]        // words/phrases printed in italics
}
```

---

## Reproducing the EPUB

Requirements: **Python 3** with `PyMuPDF` (fitz), `Pillow`, and `lxml`; **Tesseract 4+** on
`PATH`. All scripts locate the repo automatically (override with the `PT_ROOT` env var).

### Option A — rebuild from the saved artifacts (deterministic, no AI, no OCR)

The reconstructed sections are checked in, so the book can be rebuilt with one command:

```bash
python3 tools/assemble.py build      # -> "Pastoral Theology - Thomas Murphy.epub"
```

### Option B — re-run reconstruction from OCR + deltas (no AI; needs Tesseract)

```bash
tools/run_ocr.sh                              # render 300 dpi images (re-OCR is skipped if artifacts/ocr exists)
python3 tools/ocr_reconstruct.py range 4 7 preface
python3 tools/ocr_reconstruct.py range 14 501 body
python3 tools/ocr_reconstruct.py index 502 510
python3 tools/assemble.py build
```

### Option C — full pipeline from scratch, including the AI proofreading

Steps 1, 3, 4 are as above. Step 2 (`tools/wf_delta.js`) is a **Claude Code Workflow** — it
fans out one Sonnet agent per page — and must be run from within Claude Code with the
`Workflow` tool (see the header comment in `wf_delta.js` for the exact `args`). Because the
deltas are already saved in `artifacts/deltas/`, this step only needs to be re-run to
regenerate that metadata.

Verification used during development: rebuilding from artifacts reproduces the committed
`artifacts/sections/*.html` byte-for-byte, and the resulting EPUB passes well-formedness and
EPUB-structure checks (mimetype first + stored, consistent manifest/spine, resolvable nav).

---

## Accuracy and limitations

- Body text is **OCR-derived and AI-proofread** — accuracy is high but not perfect; a rare
  OCR slip may remain across the ~146,000 words.
- Formatting is best-effort: chapter titles, small-capital section headings, and italics are
  reproduced; some block quotations render as ordinary paragraphs.
- Original page numbers are dropped (meaningless in reflowable text) **except inside the Index**,
  where the numbers are the entries' data and refer to the original 1877 pagination.
- The cover is newly designed for this edition; the original scanned title page is preserved
  as a facsimile page at the front of the book.

## License

The underlying work is in the **public domain**. The designed cover (`cover.jpg`) and this
edition's scripts are provided for reuse; attribution is appreciated but not required.
