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

### Typo sweep (post-pass)

OCR of worn 19th-century type fails along known letter-confusion patterns (e↔c, rn↔m,
li↔h, u↔n, in↔m, …), producing plausible-looking typos such as `prayer-mect`. The sweep
finds and fixes these in three steps:

1. `tools/find_typo_suspects.py` — **intra-corpus confusion-pair frequency analysis**: a
   token that is *rare* in this book, while a confusion-variant of it is *common* in the
   same book, is a likely misread (`mect`×1 vs `meet`×27). Corpus frequency adapts to the
   book's own vocabulary; a dictionary (with inflection handling) is only a secondary
   signal, and dictionary words like `arc`/`clay` require far stronger evidence. Emits
   per-page hint files — candidates are **never auto-applied**.
2. `tools/wf_validate_typos.js` — one Sonnet/medium agent per suspect page validates each
   candidate against the page image (the authority) and writes confirmed/rejected verdicts.
   This is what catches the traps: `Horne` (Bishop Horne, a name), `clay` ("miry clay"),
   and page-boundary hyphen fragments (`fect`, `tive`) were all correctly rejected.
3. `tools/merge_confirmed_fixes.py` — merges confirmed fixes into the per-page deltas with
   word-boundary-safe replacement strings, then affected pages are re-reconstructed.

`tools/find_recon_drift.py` is a second, more principled detector for the same validation
step. The reconstruction re-OCRs each page (via `run_tsv`, for word geometry) and uses that
pass's text, which can differ from the plain-text OCR in `artifacts/ocr/` — the pass the
agents validated. This detector flags words the reconstructed section introduced that the
validated plain OCR reads as a common word (e.g. `thimgs`→`things`), and feeds them through
the same image validation. Heading detection is also fuzzy-matched (SequenceMatcher ≥ 0.85,
length-guarded) so an OCR error in a heading's lettered marker — `(dq)` for `(d)`, `(6)` for
`(b)` — can't discard an otherwise-correct delta heading and leave raw OCR in a `<p>`.

### Line-wrap hyphen policy

Print-era line-wrap hyphens have no place in reflowable text, so they are dissolved at
every layer (readers may still soft-hyphenate at render time via CSS `hyphens: auto`,
which is display-only):

- `dehyphen_join` (reconstruction) joins hyphen-split words within a paragraph; a small
  compound-repair list restores words whose real hyphen coincided with the line break
  (`Sabbath-school`, `prayer-meeting`).
- Delta fixes written against the raw OCR line layout are normalized at load time so they
  match the joined text (`apply_fixes` → `_fix_variants`): a fix that copied a two-line
  wrap (`"Serip-\ntures"`) is tried with the newline collapsed, and a fix that copied a
  single trailing line-wrap hyphen (`"...most im-"`, `"sue-"`) is tried with that hyphen
  dropped so the stem matches as a prefix of the whole word (`important`, `success`).
  Length-guarded so a short stem can't over-match. (This class of dead fix hid ~17 valid
  corrections the agents had already made — stray quotes like `‘This`, `reeommending`,
  `adyantageous`, `38.`→`3.`.)
- The assembler treats a `<p>` ending in a letter-hyphen as near-certain evidence of a
  false split and joins it to the following `<p>` — within and across pages, flags or
  no flags — with a guard for suspended compounds ("well- or ill-…") and the same
  compound repair after the join.
- A word-count audit (OCR words vs. reconstructed words per page) guards against text
  loss; it caught a heading-matching bug where a paragraph containing a swallowed
  centered heading was replaced by the heading alone (`split_heading` now splits such
  blocks instead, and only when the swallowed occurrence is set in capitals).

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
- Original page numbers are not shown inline, but every original page boundary is preserved as an
  invisible **EPUB page-break marker** (`epub:type="pagebreak"`), exposed through a `page-list` nav and
  a legacy NCX `pageList`. Supporting readers can show "print page N," jump to a print page, and keep
  citations stable. The **Index's page numbers are live links** to those markers.
- The cover is newly designed for this edition; the original scanned title page is preserved
  as a facsimile page at the front of the book.

## License

The underlying work is in the **public domain**. The designed cover (`cover.jpg`) and this
edition's scripts are provided for reuse; attribution is appreciated but not required.
