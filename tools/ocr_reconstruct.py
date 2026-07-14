#!/usr/bin/env python3
"""Reconstruct clean per-page HTML fragments from tesseract TSV geometry,
enhanced by per-page Sonnet/medium proofreading deltas
(artifacts/deltas/delta_p<NNN>.json: {drop, fixes, headings[{text,level}], italics}).
The body text comes from tesseract; the image-reading agents only supply small
corrections/formatting. Output: artifacts/sections/sec_p<NNN>.html (flag comments
+ blocks), consumed by assemble.py.

Usage:
  python tools/ocr_reconstruct.py range 4 7 preface     # reconstruct preface pages
  python tools/ocr_reconstruct.py range 14 501 body     # reconstruct all body pages
  python tools/ocr_reconstruct.py index 502 510         # reconstruct the two-column index
Requires: tesseract on PATH, and 300 dpi page images in work/ocr-images/ (run_ocr.sh).
"""
import os, re, subprocess, statistics, html, glob, sys, json, difflib

# Repo-relative paths (override the repo root with the PT_ROOT env var).
ROOT = os.environ.get("PT_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OCRIMG = os.path.join(ROOT, "work", "ocr-images")     # 300 dpi grayscale page PNGs (regenerable via run_ocr.sh)
DELTA = os.path.join(ROOT, "artifacts", "deltas")      # per-page AI proofreading deltas (delta_p<NNN>.json)
OUT = os.path.join(ROOT, "artifacts", "sections")      # reconstructed per-page HTML fragments (sec_p<NNN>.html)
os.makedirs(OUT, exist_ok=True)

CHAPTERS = {14:("I","Nature and Importance of Pastoral Theology"),
    38:("II","The Pastor in His Closet"),92:("III","The Pastor in the Study"),
    152:("IV","The Pastor in the Pulpit"),224:("V","The Pastor in His Personal Parochial Work"),
    274:("VI","The Pastor in the Activities of the Church"),327:("VII","The Pastor in the Progress of the Church"),
    361:("VIII","The Pastor in the Sabbath-School"),428:("IX","The Pastor in the Benevolent Work of the Church"),
    451:("X","The Pastor in the Session"),472:("XI","The Pastor in the Higher Courts of the Church"),
    492:("XII","The Pastor in His Relations to Other Denominations")}

SMALLWORDS = {"a","an","and","as","at","but","by","for","from","in","is","of","on","or",
    "the","to","up","with","his","he","be","are","it","that","this","not","nor","so"}

def title_case(s):
    s = s.strip().rstrip(".").strip()
    # keep a leading "(x)" marker
    m = re.match(r"^\((\w)\)\s*(.*)$", s)
    prefix = ""
    if m:
        prefix = "(%s) " % m.group(1).lower()
        s = m.group(2)
    words = re.split(r"(\s+)", s.lower())
    out = []
    first = True
    for tok in words:
        if tok.strip() == "":
            out.append(tok); continue
        w = tok
        if (not first) and w in SMALLWORDS:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
        first = False
    return prefix + "".join(out)

def esc(t):
    return html.escape(t, quote=False)

def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())

def load_delta(page):
    p = os.path.join(DELTA, "delta_p%03d.json" % page)
    if not os.path.exists(p):
        return None
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return None
    d.setdefault("drop", []); d.setdefault("fixes", [])
    d.setdefault("headings", []); d.setdefault("italics", [])
    return d

def _fix_variants(w, r):
    """Yield matchable forms of a delta fix. The proofreading agents wrote some fixes
    against the raw OCR line layout ("Serip-\\ntures", "...most im-"), but fixes are
    applied AFTER the lines are joined and de-hyphenated — so also try the fix with
    line-wrap hyphens dissolved and newlines collapsed to spaces."""
    yield w, r
    if "\n" in w or "\n" in r:
        dw = re.sub(r"\s*\n\s*", " ", re.sub(r"-\s*\n\s*", "", w))
        dr = re.sub(r"\s*\n\s*", " ", re.sub(r"-\s*\n\s*", "", r))
        yield dw, dr
    # a fix that copied a trailing line-wrap hyphen ("...most im-", "sue-") can't match
    # the joined text ("...most important", "success"); drop the trailing hyphen so the
    # stem matches as a prefix of the whole word. Length-guarded so a short stem (e.g.
    # "hay") can't over-match a common substring elsewhere on the page.
    wh, rh = w.rstrip(), r.rstrip()
    if wh.endswith("-") and rh.endswith("-") and len(wh[:-1].strip()) >= 4:
        yield wh[:-1], rh[:-1]

def apply_fixes(text, fixes):
    for f in fixes:
        w0, r0 = f.get("wrong"), f.get("right")
        if not w0 or r0 is None:
            continue
        for w, r in _fix_variants(w0, r0):
            if w and w != r and w in text:
                text = text.replace(w, r)
                break
    return text

# Book-wide OCR fixes not always caught by the per-page delta: rejoin compound words that
# Tesseract merged, and correct a recurring misread ("saered" -> "sacred").
COMMON_FIXES = [
    (r"\bSabbathschools\b", "Sabbath-schools"), (r"\bSabbathschool\b", "Sabbath-school"),
    (r"\bPrayermeetings\b", "Prayer-meetings"), (r"\bprayermeetings\b", "prayer-meetings"),
    (r"\bPrayermeeting\b", "Prayer-meeting"),   (r"\bprayermeeting\b", "prayer-meeting"),
    (r"\bsaered\b", "sacred"), (r"\bSaered\b", "Sacred"),
]

def apply_common(text):
    for pat, rep in COMMON_FIXES:
        text = re.sub(pat, rep, text)
    return text

def apply_italics(text_html_escaped, italics):
    # wrap whole-word italic phrases (escaped) in <em>; longest first
    for phrase in sorted([p for p in italics if p and len(p) >= 2], key=len, reverse=True):
        esc_p = esc(phrase)
        pat = re.compile(r"(?<![\w>])" + re.escape(esc_p) + r"(?![\w<])")
        text_html_escaped = pat.sub("<em>" + esc_p + "</em>", text_html_escaped, count=1)
    return text_html_escaped

def run_tsv(imgpath):
    out = subprocess.run(["tesseract", imgpath, "stdout", "--psm", "6", "--oem", "1",
                          "-l", "eng", "tsv"], capture_output=True, text=True).stdout
    rows = [r.split("\t") for r in out.splitlines() if r.strip()]
    if not rows:
        return []
    H = {h: i for i, h in enumerate(rows[0])}
    lines = {}
    for r in rows[1:]:
        if len(r) <= H["text"]:
            continue
        if r[H["level"]] != "5":
            continue
        txt = r[H["text"]]
        if txt.strip() == "":
            continue
        key = (int(r[H["block_num"]]), int(r[H["par_num"]]), int(r[H["line_num"]]))
        lines.setdefault(key, []).append({
            "left": int(r[H["left"]]), "top": int(r[H["top"]]),
            "width": int(r[H["width"]]), "height": int(r[H["height"]]),
            "text": txt})
    L = []
    for key in sorted(lines):
        ws = sorted(lines[key], key=lambda x: x["left"])
        L.append({"block": key[0], "par": key[1], "line": key[2],
                  "text": " ".join(w["text"] for w in ws),
                  "left": min(w["left"] for w in ws),
                  "right": max(w["left"] + w["width"] for w in ws),
                  "top": min(w["top"] for w in ws),
                  "height": max(w["height"] for w in ws)})
    return L

def caps_ratio(t):
    letters = [c for c in t if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if c.isupper()) / len(letters)

def dehyphen_join(lines):
    """Join a paragraph's lines into one string, de-hyphenating line-end splits."""
    parts = [l["text"].strip() for l in lines]
    s = parts[0]
    for nxt in parts[1:]:
        if re.search(r"[A-Za-z]-$", s):
            s = s[:-1] + nxt
        elif s.endswith("—") or nxt.startswith("—"):
            s = s + nxt
        else:
            s = s + " " + nxt
    return re.sub(r"\s+", " ", s).strip()

def reconstruct(page, kind="body"):
    imgpath = os.path.join(OCRIMG, "p%03d.png" % page)
    L = run_tsv(imgpath)
    if not L:
        return None
    lefts = [l["left"] for l in L]
    rights = [l["right"] for l in L]
    left_min = min(lefts)
    body_left = statistics.median([x for x in lefts if x < left_min + 90]) if lefts else left_min
    body_right = max(rights)
    width = max(body_right - body_left, 1)
    page_top = min(l["top"] for l in L)
    page_bottom = max(l["top"] + l["height"] for l in L)
    pheight = page_bottom - page_top
    opener = CHAPTERS.get(page) if kind == "body" else None
    ch_title_up = re.sub(r"[^A-Z ]", "", opener[1].upper()) if opener else None
    min_top = min(l["top"] for l in L)
    delta = load_delta(page) or {"drop": [], "fixes": [], "headings": [], "italics": []}
    drop_norms = set(norm(d) for d in delta["drop"] if norm(d))
    heading_index = [(norm(h.get("text", "")), h.get("text", ""), h.get("level", "h2"))
                     for h in delta["headings"] if norm(h.get("text", ""))]

    def is_centered(l):
        return (l["left"] - body_left) > width * 0.10 and (body_right - l["right"]) > width * 0.10

    def drop_line(l, is_first):
        t = l["text"].strip()
        # delta-specified drops (running heads / page numbers the agent flagged)
        if drop_norms and norm(t) in drop_norms:
            return True
        # page number / signature: pure number or single letter
        if re.fullmatch(r"[0-9]{1,4}", t):
            return True
        if re.fullmatch(r"[A-Za-z0-9]", t):
            return True
        # running head: the topmost line on any non-opener page (title +/- page number)
        is_topmost = (l["top"] - min_top) <= 14
        if not opener and is_topmost and (l["top"] - page_top) < pheight * 0.09 \
                and caps_ratio(t) > 0.35 and len(t.split()) <= 8:
            return True
        # running head: near top and centered/offset (recto pages)
        near_top = (l["top"] - page_top) < pheight * 0.06
        if near_top and is_centered(l) and caps_ratio(t) > 0.4 and len(t.split()) <= 8:
            return True
        # opener special lines
        if opener:
            up = re.sub(r"[^A-Z ]", "", t.upper())
            if "PASTORAL THEOLOGY" in up and near_top:
                return True
            if re.match(r"^CHAPTER\s+[IVXLC]+", t.strip(), re.I):
                return True
            if ch_title_up and up.strip() and (up.strip() in ch_title_up or ch_title_up in up.strip()):
                return True
        return False

    # filter lines
    kept = []
    for i, l in enumerate(L):
        if drop_line(l, i == 0):
            continue
        kept.append(l)
    if not kept:
        return ("", False, False)

    # group into paragraphs by (block,par); split when a line is indented (new para)
    blocks = []
    cur = []
    cur_key = None
    for l in kept:
        key = (l["block"], l["par"])
        indented = (l["left"] - body_left) > width * 0.035
        if cur and (key != cur_key or (indented and len(cur) >= 1 and l is not cur[0])):
            # new paragraph if par changed OR this line is indented (start of new para)
            if key != cur_key or indented:
                blocks.append(cur); cur = []
        cur.append(l); cur_key = key
    if cur:
        blocks.append(cur)

    def match_heading(text):
        """Match a block to a delta heading. Only a block whose text is essentially the
        heading itself (or a fragment of it) qualifies — the length guard is critical:
        a long paragraph that merely CONTAINS the heading (tesseract sometimes merges
        the centered heading line into a body block) must be SPLIT, never replaced,
        or the paragraph's body text is silently lost."""
        n = norm(text)
        if not n:
            return None
        for hn, htext, hlevel in heading_index:
            if len(n) > len(hn) + 12:
                continue
            lvl = hlevel if hlevel in ("h2", "h3") else "h2"
            if n == hn or (len(n) >= 6 and (
                    n.startswith(hn[:14]) or hn.startswith(n[:14]) or hn in n or n in hn)):
                return (htext, lvl)
            # fuzzy fallback: an OCR error inside the heading (e.g. marker "(dq)" for "(d)",
            # or "THe" for "The") breaks the strict prefix/substring checks even though the
            # block clearly IS this heading. The length guard keeps this from matching body
            # paragraphs; a high similarity ratio keeps it from matching a different heading.
            if len(n) >= 12 and difflib.SequenceMatcher(None, n, hn).ratio() >= 0.85:
                return (htext, lvl)
        return None

    def split_heading(text):
        """If a long paragraph swallowed a heading, split it into (before, heading, after).
        Returns None when no full heading is found — then the block stays a paragraph
        (keeping the text inline is always better than losing it)."""
        for hn, htext, hlevel in heading_index:
            n = norm(text)
            if len(n) <= len(hn) + 12 or (hn not in n):
                continue
            words = [re.escape(w) for w in re.findall(r"[A-Za-z0-9]+", htext)]
            if len(words) < 2:
                continue
            pat = re.compile(r"\(?\s*" + r"[\s.:;,()\-]{0,4}".join(words) + r"\s*\.?\s*",
                             re.IGNORECASE)
            m = pat.search(text)
            # the printed heading is set in (small) capitals, so the swallowed occurrence
            # must be mostly caps — otherwise it is the same phrase in ordinary body prose
            # (e.g. "...appreciate the importance of the Sabbath-school work") and must
            # NOT be split.
            if m and caps_ratio(m.group(0)) >= 0.5:
                lvl = hlevel if hlevel in ("h2", "h3") else "h2"
                return text[:m.start()].strip(), (htext, lvl), text[m.end():].strip()
        return None

    def emit_heading(htext, level):
        tc = title_case(htext)
        if re.match(r"^\(\s*[a-zA-Z]\s*\)", htext):
            level = "h3"
        hblock = (level, "<%s>%s</%s>" % (level, esc(tc), level))
        # a multi-line heading can split into consecutive blocks that both match the
        # same delta heading -> collapse consecutive identical headings
        if html_blocks and html_blocks[-1][0] in ("h2", "h3") and html_blocks[-1][1] == hblock[1]:
            return
        html_blocks.append(hblock)

    def emit_paragraph(text, para):
        inner = apply_italics(esc(text), delta["italics"])
        html_blocks.append(("p", "<p>" + inner + "</p>", para))

    html_blocks = []
    for para in blocks:
        text = dehyphen_join(para)
        text = apply_fixes(text, delta["fixes"])
        text = apply_common(text)
        if not text:
            continue
        # drop junk (stray stamp/marks with almost no letters)
        if sum(c.isalpha() for c in text) < 2:
            continue
        # the "PREFACE" title is re-added by the assembler
        if kind == "preface" and norm(text) == "preface":
            continue
        short = len(para) <= 3
        centered_any = any(is_centered(l) for l in para)
        lettered = re.match(r"^\(\s*[a-zA-Z]\s*\)", text)
        dh = match_heading(text)
        if dh:
            emit_heading(dh[0], dh[1])
            continue
        sp = split_heading(text)
        if sp:
            before, (htext, lvl), after = sp
            if before:
                emit_paragraph(before, para)
            emit_heading(htext, lvl)
            if after:
                emit_paragraph(after, para)
            continue
        looks_heading = (short and centered_any and (caps_ratio(text) > 0.55 or lettered)) or \
                        (lettered and caps_ratio(text) > 0.5)
        if looks_heading:
            tc = title_case(text)
            lvl = "h3" if lettered else "h2"
            html_blocks.append((lvl, "<%s>%s</%s>" % (lvl, esc(tc), lvl)))
        else:
            emit_paragraph(text, para)

    # continuation flags
    starts_mid = False
    ends_mid = False
    content = [b for b in html_blocks]
    if content and content[0][0] == "p":
        first_para = content[0][2]
        if (first_para[0]["left"] - body_left) <= width * 0.035:
            starts_mid = True   # first line not indented -> continues prev page
    if content and content[-1][0] == "p":
        last_para = content[-1][2]
        last_line = last_para[-1]
        if last_line["right"] >= body_right - width * 0.05 or last_line["text"].rstrip().endswith("-"):
            ends_mid = True

    body_html = "\n".join(b[1] for b in html_blocks)
    return (body_html, starts_mid, ends_mid)

OVERRIDES = os.path.join(ROOT, "artifacts", "overrides")   # hand-authored page fragments that
#   the automated pipeline cannot produce (e.g. tables). If present, used verbatim.

def write_page(page, kind="body"):
    ov = os.path.join(OVERRIDES, "sec_p%03d.html" % page)
    if os.path.exists(ov):
        import shutil
        shutil.copy(ov, os.path.join(OUT, "sec_p%03d.html" % page))
        return True
    res = reconstruct(page, kind)
    if res is None:
        return False
    body_html, sm, em = res
    out = ("<!-- startsMidParagraph: %s -->\n<!-- endsMidParagraph: %s -->\n%s\n"
           % ("true" if sm else "false", "true" if em else "false", body_html))
    open(os.path.join(OUT, "sec_p%03d.html" % page), "w", encoding="utf-8").write(out)
    return True

def _tsv_from_image(imgpath):
    """run_tsv but for an arbitrary image path (returns line dicts)."""
    return run_tsv(imgpath)

def index_column_blocks(imgpath):
    """OCR one index column image; return list of ('h2'|'p', text)."""
    L = run_tsv(imgpath)
    if not L:
        return []
    # group by (block,par)
    paras, cur, key = [], [], None
    for l in L:
        k = (l["block"], l["par"])
        if cur and k != key:
            paras.append(cur); cur = []
        cur.append(l); key = k
    if cur:
        paras.append(cur)
    out = []
    for para in paras:
        text = dehyphen_join(para).strip()
        if not text:
            continue
        # drop running head / page-number fragments
        up = text.upper()
        if ("INDEX" in up and len(text.split()) <= 3) or re.fullmatch(r"[0-9]{1,4}\s*IN[DI].*", up) \
                or re.fullmatch(r"[0-9]{1,4}", text):
            continue
        # letter divider: a single capital, optionally with a period
        if re.fullmatch(r"[A-Z]\.?", text):
            out.append(("h2", text[0]))
            continue
        # strip a leading stray page-number+INDEX fragment on first entry
        text = re.sub(r"^[0-9]{1,4}\s+IN[DIL].{0,3}\s+", "", text)
        out.append(("p", text))
    return out

def build_index_page(page):
    from PIL import Image
    imgpath = os.path.join(OCRIMG, "p%03d.png" % page)
    im = Image.open(imgpath)
    w, h = im.size
    top = int(h * 0.058)          # skip the running-head band
    mid = int(w * 0.505)
    Lc = os.path.join(OCRIMG, "_idxL.png"); Rc = os.path.join(OCRIMG, "_idxR.png")
    im.crop((0, top, mid, h)).save(Lc)
    im.crop((mid, top, w, h)).save(Rc)
    delta = load_delta(page) or {"fixes": [], "drop": []}
    blocks = index_column_blocks(Lc) + index_column_blocks(Rc)
    htmlb = []
    for typ, text in blocks:
        text = apply_fixes(text, delta.get("fixes", []))
        text = text.replace("|", " ")
        # remove OCR hyphen glitches inside words (em-dash or doubled marks) but keep real hyphens
        text = re.sub(r"(?<=[a-z])(?:—|--|-—|—-|—)(?=[a-z]{2,})", "", text)
        text = apply_common(text)
        text = re.sub(r"\s+([;,.])", r"\1", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        # strip leaked running-head fragments: "506 IN] ", "508 INDEX", "x. 507 ", "IND A."
        text = re.sub(r"^\s*[A-Za-z]?\.?\s*\d{2,4}\s*IN[\]A-Za-z.]*\s*", "", text)
        text = re.sub(r"^\s*IN(?:DEX|\])[.A-Za-z]*\s+", "", text)
        text = re.sub(r"^\s*[A-Za-z]?\.?\s*\d{2,4}\s+(?=[a-z])", "", text)
        text = re.sub(r"^IND(?:EX)?\.?\s+[A-Z]\.?\s+", "", text)
        text = text.strip()
        # keep only real entries (contain a page number); drop garbage/dividers (dividers synthesized later)
        if not re.search(r"\d", text) or len(text) < 4:
            continue
        htmlb.append('<p class="ie">' + esc(text) + "</p>")
    # index entries don't paragraph-merge across pages the way prose does
    out = ("<!-- startsMidParagraph: false -->\n<!-- endsMidParagraph: false -->\n"
           + "\n".join(htmlb) + "\n")
    open(os.path.join(OUT, "sec_p%03d.html" % page), "w", encoding="utf-8").write(out)
    return len(htmlb)

if __name__ == "__main__":
    # ranges: preface 4-7, body 14-501, index handled separately
    args = sys.argv[1:]
    if args and args[0] == "range":
        a, b, kind = int(args[1]), int(args[2]), (args[3] if len(args) > 3 else "body")
        n = 0
        for p in range(a, b + 1):
            if os.path.exists(os.path.join(OCRIMG, "p%03d.png" % p)):
                if write_page(p, kind):
                    n += 1
        print("wrote", n, "pages", a, "-", b)
    elif args and args[0] == "index":
        a, b = int(args[1]), int(args[2])
        tot = 0
        for p in range(a, b + 1):
            if os.path.exists(os.path.join(OCRIMG, "p%03d.png" % p)):
                tot += build_index_page(p)
        print("index: wrote", b - a + 1, "pages,", tot, "blocks")
    else:
        print("usage: ocr_reconstruct.py range <a> <b> [kind] | index <a> <b>")
