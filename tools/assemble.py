#!/usr/bin/env python3
"""Assemble per-page OCR-corrected HTML fragments into a clean EPUB.

Sections are files named sec_p<NNN>.html (NNN = 0-based PDF page index),
each starting with two flag comments then block elements.

Reads artifacts/sections/, assets/original-title-page.png, and cover.jpg; writes
"Pastoral Theology - Thomas Murphy.epub" to the repo root. Requires: lxml, Pillow.

Usage:
  python tools/assemble.py check                 # report presence of section files
  python tools/assemble.py preview <ROMAN>       # stitch one chapter -> work/build/preview_ch<R>.html
  python tools/assemble.py build                 # build the full EPUB
"""
import os, re, sys, glob, html, zipfile, datetime
import lxml.html
from lxml import etree

# Repo-relative paths (override the repo root with the PT_ROOT env var).
ROOT = os.environ.get("PT_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "artifacts", "sections")      # reconstructed per-page HTML fragments (input)
BUILD = os.path.join(ROOT, "work", "build")            # scratch build tree + rendered previews
ASSETS = os.path.join(ROOT, "assets")                  # original-title-page.png (facsimile)
COVER_SRC = os.path.join(ROOT, "cover.jpg")            # designed cover supplied for this edition
EPUB_OUT = os.path.join(ROOT, "Pastoral Theology - Thomas Murphy.epub")
os.makedirs(BUILD, exist_ok=True)

# (roman, title, first_page_idx, last_page_idx)  -- 0-based PDF page indices
CHAPTERS = [
    ("I",    "Nature and Importance of Pastoral Theology",      14,  37),
    ("II",   "The Pastor in His Closet",                        38,  91),
    ("III",  "The Pastor in the Study",                         92, 151),
    ("IV",   "The Pastor in the Pulpit",                       152, 223),
    ("V",    "The Pastor in His Personal Parochial Work",      224, 273),
    ("VI",   "The Pastor in the Activities of the Church",     274, 326),
    ("VII",  "The Pastor in the Progress of the Church",       327, 360),
    ("VIII", "The Pastor in the Sabbath-School",               361, 427),
    ("IX",   "The Pastor in the Benevolent Work of the Church",428, 450),
    ("X",    "The Pastor in the Session",                      451, 471),
    ("XI",   "The Pastor in the Higher Courts of the Church",  472, 491),
    ("XII",  "The Pastor in His Relations to Other Denominations",492, 501),
]
PREFACE_PAGES = list(range(4, 8))     # 4..7
INDEX_PAGES = list(range(502, 511))   # 502..510

# --------------------------- fragment parsing -------------------------------

def sec_path(page):
    return os.path.join(OUT, "sec_p%03d.html" % page)

def read_page(page):
    """Return (starts_mid, ends_mid, [block_xml_strings]) or None if missing/empty."""
    p = sec_path(page)
    if not os.path.exists(p):
        return None
    raw = open(p, encoding="utf-8").read().strip()
    if not raw:
        return None
    raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    starts = bool(re.search(r"<!--\s*startsMidParagraph:\s*true\s*-->", raw, re.I))
    ends = bool(re.search(r"<!--\s*endsMidParagraph:\s*true\s*-->", raw, re.I))
    body = re.sub(r"<!--\s*(?:starts|ends)MidParagraph:.*?-->", "", raw, flags=re.I)
    return starts, ends, blocks_from_fragment(body)

def blocks_from_fragment(fragment_html):
    fragment_html = fragment_html.strip()
    if not fragment_html:
        return []
    fragment_html = re.sub(r"<br\s*>", "<br/>", fragment_html)
    fragment_html = re.sub(r"<hr\s*>", "<hr/>", fragment_html)
    nodes = lxml.html.fragments_fromstring(fragment_html)
    out = []
    for n in nodes:
        if isinstance(n, str):
            t = n.strip()
            if t:
                out.append("<p>" + html.escape(t, quote=False) + "</p>")
            continue
        n.tail = None
        out.append(etree.tostring(n, method="xml", encoding="unicode").strip())
    return out

P_INNER = re.compile(r"^<p\b[^>]*>(.*)</p>\s*$", re.S)
def is_p(b): return P_INNER.match(b) is not None
def p_inner(b):
    m = P_INNER.match(b); return m.group(1) if m else None

def join_boundary(left, right):
    left = left.rstrip(); right = right.lstrip()
    if re.search(r"[A-Za-z0-9]-$", left):
        return left[:-1].rstrip() + right          # hyphenated word split across pages
    if left.endswith("—") or right.startswith("—"):
        return left + right
    return left + " " + right

def printed_of(pg):
    """Printed page number for a PDF page index (numbered pages only), else None.
    Offset is -1 across preface (idx 4-7 -> 3-6), body (14-501 -> 13-500), index (502-510 -> 501-509)."""
    if pg in PREFACE_PAGES or 14 <= pg <= 501 or pg in INDEX_PAGES:
        return pg - 1
    return None

def pagebreak_span(n):
    """An invisible EPUB 3 print-page marker for printed page n."""
    return ('<span epub:type="pagebreak" role="doc-pagebreak" id="pg%d" '
            'aria-label="%d" title="%d"></span>' % (n, n, n))

def _insert_anchor(block, anchor):
    """Place an inline anchor just inside the opening tag of a block element."""
    m = re.match(r"(<[a-zA-Z][^>]*>)(.*)", block, re.S)
    return (m.group(1) + anchor + m.group(2)) if m else (anchor + block)

def stitch_pages(pages, anchors=True):
    """Stitch consecutive page indices, merging paragraphs across seams. When `anchors`,
    insert an invisible pagebreak marker at the start of each numbered page's content and
    return the list of printed page numbers marked (in order)."""
    merged, prev_end, missing, marks = [], False, [], []
    for pg in pages:
        res = read_page(pg)
        if res is None:
            missing.append(pg); prev_end = False; continue
        starts, ends, blocks = res
        pn = printed_of(pg) if anchors else None
        anchor = pagebreak_span(pn) if pn is not None else ""
        if anchor:
            marks.append(pn)
        if merged and prev_end and starts and blocks and is_p(merged[-1]) and is_p(blocks[0]):
            # paragraph continues across the seam: put the marker at the join point
            L, R = p_inner(merged[-1]).rstrip(), p_inner(blocks[0]).lstrip()
            if re.search(r"[A-Za-z0-9]-$", L):
                inner = L[:-1].rstrip() + anchor + R
            elif L.endswith("—") or R.startswith("—"):
                inner = L + anchor + R
            else:
                inner = L + (" " if anchor else "") + anchor + R if anchor else L + " " + R
            merged[-1] = "<p>" + inner + "</p>"
            blocks = blocks[1:]
        elif anchor and blocks:
            blocks = [_insert_anchor(blocks[0], anchor)] + blocks[1:]
        merged.extend(blocks)
        prev_end = ends
    return merged, missing, marks

# ------------------------------- styling ------------------------------------

CSS = """@charset "utf-8";
html { font-size: 100%; }
body { font-family: Georgia, "Times New Roman", serif; line-height: 1.5;
       margin: 0 5%; text-align: justify; hyphens: auto; -webkit-hyphens: auto; }
h1, h2, h3 { text-align: center; font-weight: normal; page-break-after: avoid; }
.chapnum { text-align: center; letter-spacing: 0.25em; font-size: 0.95em; margin: 2.4em 0 0.5em; }
h1.chaptitle { font-size: 1.3em; font-style: italic; letter-spacing: 0.02em; margin: 0.2em 6% 0.2em; line-height: 1.35; }
h2 { font-variant: small-caps; font-size: 1.03em; letter-spacing: 0.05em; margin: 1.7em 0 0.7em; }
h3 { font-variant: small-caps; font-size: 0.95em; letter-spacing: 0.03em; margin: 1.3em 5% 0.6em; }
p { margin: 0; text-indent: 1.4em; }
h1 + p, h2 + p, h3 + p, hr + p, blockquote + p, .first { text-indent: 0; }
.sc { font-variant: small-caps; }
em { font-style: italic; }
blockquote { margin: 0.8em 6%; font-size: 0.97em; }
blockquote p { text-indent: 0; margin: 0.4em 0; }
p.verse { text-indent: 0; margin: 0.6em 8%; }
aside.fn { font-size: 0.85em; margin: 0.6em 3%; border-top: 1px solid #999; padding-top: 0.3em; }
hr.rule { width: 20%; margin: 1.2em auto 1.6em; border: 0; border-top: 1px solid #555; }
.tp { text-align: center; }
.tp .t1 { font-size: 1.9em; letter-spacing: 0.08em; margin-top: 2.2em; }
.tp .t2 { font-size: 1.2em; letter-spacing: 0.16em; margin-top: 1.5em; }
.tp .t3 { font-size: 0.82em; letter-spacing: 0.2em; margin-top: 0.5em; }
.tp .t4 { font-size: 1.15em; letter-spacing: 0.06em; margin-top: 1.6em; }
.tp .by { font-size: 0.78em; margin-top: 2em; letter-spacing: 0.1em; }
.tp .auth { font-size: 1.15em; letter-spacing: 0.08em; margin-top: 0.4em; }
.tp .small { font-size: 0.76em; letter-spacing: 0.08em; margin-top: 0.2em; }
.tp .pub { font-size: 0.9em; margin-top: 3em; letter-spacing: 0.05em; line-height: 1.8; }
.copyright { text-align: center; font-size: 0.82em; margin-top: 30%; line-height: 1.9; }
h1.fm { font-size: 1.6em; letter-spacing: 0.05em; margin: 1.4em 0 0.3em; }
nav#toc ol { list-style: none; padding-left: 0; }
nav#toc li { margin: 0.4em 0; text-align: left; }
nav#toc a { text-decoration: none; color: inherit; }
h2.idx-letter { font-weight: bold; font-variant: normal; margin: 1.3em 0 0.5em; letter-spacing: 0.12em; }
.indexbody p.ie { text-indent: -1.1em; margin: 0.12em 0 0.12em 1.1em; text-align: left; }
.indexbody a { color: inherit; text-decoration: none; }
span[role="doc-pagebreak"] { display: none; }
table.chrono { border-collapse: collapse; margin: 1.3em auto; font-size: 0.88em; line-height: 1.3; }
table.chrono th, table.chrono td { border: 1px solid #777; padding: 0.12em 0.55em; vertical-align: top; }
table.chrono th { font-variant: small-caps; font-weight: normal; text-align: center; }
table.chrono td:nth-child(1), table.chrono th:nth-child(1) { text-align: left; }
table.chrono td:nth-child(2), table.chrono td:nth-child(4) { text-align: right; }
table.chrono td:nth-child(3) { text-align: left; }
.about h2 { text-align: left; font-variant: normal; font-size: 1.12em; letter-spacing: 0; margin: 1.5em 0 0.4em; }
.about p { text-indent: 0; margin: 0.7em 0; }
.about a { color: inherit; }
.colophon { font-size: 0.85em; font-style: italic; color: #555; margin-top: 1.8em; border-top: 1px solid #ccc; padding-top: 0.8em; }
"""

XHTML = ('<?xml version="1.0" encoding="utf-8"?>\n<!DOCTYPE html>\n'
    '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
    'xml:lang="en" lang="en">\n<head>\n<meta charset="utf-8"/>\n<title>%(title)s</title>\n'
    '<link rel="stylesheet" type="text/css" href="style.css"/>\n</head>\n<body>\n%(body)s\n</body>\n</html>\n')

def doc(title, body):
    return XHTML % {"title": html.escape(title), "body": body}

def validate(s, label):
    try:
        etree.fromstring(s.encode("utf-8")); return True
    except Exception as e:
        print("  !! INVALID XML in %s: %s" % (label, str(e)[:200])); return False

def chapter_doc(roman, title, a, b):
    blocks, missing, marks = stitch_pages(range(a, b + 1))
    if missing:
        print("  Ch %s missing pages: %s" % (roman, missing))
    if not blocks:
        return None, missing, marks
    head = ('<section epub:type="chapter">\n<div class="chapnum">CHAPTER %s.</div>\n'
            '<h1 class="chaptitle" id="ch%s">%s</h1>\n<hr class="rule"/>\n') % (roman, roman, html.escape(title))
    return doc("Chapter %s. %s" % (roman, title), head + "\n".join(blocks) + "\n</section>"), missing, marks

def titlepage_doc():
    b = ('<section epub:type="titlepage" class="tp">\n'
         '<p class="t1">PASTORAL THEOLOGY</p>\n<p class="t2">THE PASTOR</p>\n'
         '<p class="t3">IN THE</p>\n<p class="t4">VARIOUS DUTIES OF HIS OFFICE</p>\n'
         '<p class="by">BY</p>\n<p class="auth">THOMAS MURPHY, D.D.</p>\n'
         '<p class="small">PASTOR OF THE FRANKFORD PRESBYTERIAN CHURCH, PHILADELPHIA</p>\n'
         '<p class="pub">PHILADELPHIA<br/>PRESBYTERIAN BOARD OF PUBLICATION<br/>1334 CHESTNUT STREET</p>\n'
         '</section>')
    return doc("Pastoral Theology", b)

def copyright_doc():
    b = ('<section epub:type="copyright-page">\n<div class="copyright">\n'
         '<p>Entered according to Act of Congress, in the year 1877, by</p>\n'
         '<p>THE TRUSTEES OF THE PRESBYTERIAN BOARD OF PUBLICATION,</p>\n'
         '<p>In the Office of the Librarian of Congress, at Washington.</p>\n'
         '<p style="margin-top:2.5em;">Westcott &amp; Thomson,<br/>'
         '<em>Stereotypers and Electrotypers, Philada.</em></p>\n</div>\n</section>')
    return doc("Copyright", b)

def preface_doc():
    blocks, missing, marks = stitch_pages(PREFACE_PAGES)
    if missing: print("  Preface missing pages:", missing)
    if not blocks: return None, []
    b = ('<section epub:type="preface">\n<h1 class="fm" id="preface">Preface</h1>\n'
         '<hr class="rule"/>\n' + "\n".join(blocks) + "\n</section>")
    return doc("Preface", b), marks

def linkify_index_pages(inner, page_href):
    """Turn standalone page numbers in an index entry into links to their pagebreak anchors.
    Only text nodes are touched — digits inside tags (attributes) are left alone."""
    def repl(m):
        n = int(m.group(0))
        href = page_href.get(n)
        return '<a href="%s">%d</a>' % (href, n) if href else m.group(0)
    parts = re.split(r"(<[^>]*>)", inner)          # even = text, odd = tags
    for i in range(0, len(parts), 2):
        parts[i] = re.sub(r"\b\d{1,3}\b", repl, parts[i])
    return "".join(parts)

def index_doc(page_href=None):
    blocks, missing, marks = stitch_pages(INDEX_PAGES)
    if missing: print("  Index missing pages:", missing)
    if not blocks: return None, []
    # keep only entries; synthesize clean letter dividers, robust to single garbled
    # first-letters: a real section is a RUN of >=2 consecutive entries sharing a first letter.
    entries = [b for b in blocks if b.startswith('<p class="ie"')]
    def first_letter(e):
        m = re.search(r'<p class="ie">\s*(?:<span[^>]*>)?\s*([A-Za-z])', e)
        return m.group(1).upper() if m else None
    fl = [first_letter(e) for e in entries]
    emitted, out = set(), []
    for i, e in enumerate(entries):
        if page_href:   # link the page numbers inside this entry
            m = re.match(r'(<p class="ie">)(.*)(</p>)\s*$', e, re.S)
            if m:
                e = m.group(1) + linkify_index_pages(m.group(2), page_href) + m.group(3)
        L = fl[i]
        nxt = fl[i + 1] if i + 1 < len(entries) else None
        if L and L not in emitted and L == nxt:   # first entry of a run of the same letter
            out.append('<h2 class="idx-letter">%s</h2>' % L)
            emitted.add(L)
        out.append(e)
    b = ('<section epub:type="index" class="indexbody">\n<h1 class="fm" id="index">Index</h1>\n'
         '<hr class="rule"/>\n' + "\n".join(out) + "\n</section>")
    return doc("Index", b), marks

def about_doc():
    b = ['<section epub:type="preamble" class="about">',
      '<h1 class="fm" id="about">About This Edition</h1>',
      '<hr class="rule"/>',
      '<p class="first">This is a digitally reconstructed reading edition of Thomas Murphy’s '
      '<em>Pastoral Theology: The Pastor in the Various Duties of His Office</em>, first published '
      'in 1877 by the Presbyterian Board of Publication, Philadelphia. The work is in the public domain.</p>',
      '<h2>Source</h2>',
      '<p class="first">It was produced from the scanned page images of the original book, distributed as a '
      'PDF by Log College Press at '
      '<a href="http://library.logcollegepress.com/Murphy%2C+Thomas%2C+Pastoral+Theology+A.pdf">'
      'library.logcollegepress.com</a> (a scan of the copy held by Princeton Theological Seminary and '
      'archived by the Internet Archive as item <em>pastoraltheology00murp</em>).</p>',
      '<h2>How this edition was made</h2>',
      '<p class="first">The source file is a scanned facsimile — page images with an unreliable, '
      'error-filled embedded text layer. To turn it into clean, reflowable e-book text, an automated '
      'pipeline was run under <em>Claude Code</em>, Anthropic’s command-line coding tool. The steps were:</p>',
      '<p>1. <em>Page rendering.</em> Every page of the PDF was rendered to a high-resolution image.</p>',
      '<p>2. <em>Optical character recognition.</em> Each page image was processed with the open-source '
      '<em>Tesseract</em> OCR engine (version 4, LSTM) to produce a first-pass transcription.</p>',
      '<p>3. <em>Page-by-page proofreading by AI.</em> For every page, a separate agent powered by '
      '<em>Claude Sonnet</em> (Anthropic), running at “medium” reasoning effort, examined the '
      'original page image alongside the OCR output and returned a small set of targeted corrections: '
      'fixing misread characters, identifying section headings, marking italicized text, and flagging '
      'running heads and page numbers for removal. The page image — not the raw OCR — was treated '
      'as the authority.</p>',
      '<p>4. <em>Reconstruction and assembly.</em> The corrected text was recombined with each page’s '
      'layout geometry to rebuild paragraphs, headings, and chapter structure, then packaged into this EPUB '
      'with a newly generated table of contents. This orchestration and all of the assembly code were '
      'carried out by <em>Claude Opus 4.8</em> (Anthropic).</p>',
      '<p>A note on method: the text was <em>not</em> generated by having a language model retype the book. '
      'Anthropic’s models decline to reproduce book-length text verbatim, and a content filter enforces '
      'this. The AI acted only as a proofreader of the machine OCR against the page images — supplying '
      'corrections and formatting, never the underlying text.</p>',
      '<h2>Accuracy and limitations</h2>',
      '<p class="first">The body text is OCR-derived and AI-proofread: accuracy is high but not perfect, and '
      'occasional OCR errors may remain. Formatting is preserved on a best-effort basis — chapter titles, '
      'small-capital section headings, and italics are reproduced, while some block quotations appear as '
      'ordinary paragraphs. Original print page numbers are not shown in the running text (they are meaningless '
      'in reflowable type), but each original page boundary is preserved as an invisible page marker, so a '
      'reading system that supports it can show “print page N,” jump to a given print page, and keep citations '
      'stable; the Index’s page numbers are live links to those markers. The cover is newly designed for this '
      'edition; the original scanned title page is preserved as a facsimile at the front of the book.</p>',
      '<p class="colophon">Prepared July 2026 with Claude Code (orchestration by Claude Opus 4.8; per-page '
      'proofreading by Claude Sonnet at medium effort) and Tesseract OCR.</p>',
      '</section>']
    return doc("About This Edition", "\n".join(b))

def cover_section(imgfile, alt):
    return ('<section epub:type="cover"><img src="%s" alt="%s" '
            'style="max-width:100%%;max-height:100%%;height:auto;display:block;margin:0 auto;"/></section>'
            % (imgfile, html.escape(alt)))

def origcover_doc(imgfile):
    b = ('<section epub:type="frontispiece"><figure style="margin:0;text-align:center;">'
         '<img src="%s" alt="Original title page of the 1877 edition" '
         'style="max-width:100%%;height:auto;display:block;margin:0 auto;"/>'
         '<figcaption style="font-size:0.8em;font-style:italic;margin-top:0.6em;color:#555;">'
         'Title page of the original 1877 edition.</figcaption></figure></section>')
    return doc("Original Title Page", b % imgfile)

def nav_doc(docs, present, first_content, page_list=None):
    li = ['<li><a href="titlepage.xhtml">Title Page</a></li>']
    if "origcover.xhtml" in docs: li.append('<li><a href="origcover.xhtml">Original Title Page (facsimile)</a></li>')
    if "about.xhtml" in docs: li.append('<li><a href="about.xhtml">About This Edition</a></li>')
    if "preface.xhtml" in docs: li.append('<li><a href="preface.xhtml">Preface</a></li>')
    for roman, title, a, b in CHAPTERS:
        if roman in present:
            li.append('<li><a href="ch%s.xhtml">Chapter %s. %s</a></li>' % (roman, roman, html.escape(title)))
    if "index.xhtml" in docs: li.append('<li><a href="index.xhtml">Index</a></li>')
    nav = ('<nav epub:type="toc" id="toc" role="doc-toc">\n<h1 class="fm">Contents</h1>\n<ol>\n'
           + "\n".join(li) + "\n</ol>\n</nav>\n"
           '<nav epub:type="landmarks" id="landmarks" hidden="hidden">\n<ol>\n'
           '<li><a epub:type="toc" href="nav.xhtml">Table of Contents</a></li>\n'
           '<li><a epub:type="bodymatter" href="%s">Start of Content</a></li>\n</ol>\n</nav>\n' % first_content)
    if page_list:
        pl = "\n".join('<li><a href="%s">%d</a></li>' % (href, n) for n, href in page_list)
        nav += ('<nav epub:type="page-list" id="page-list" role="doc-pagelist" hidden="hidden">\n'
                '<h1>List of Pages</h1>\n<ol>\n' + pl + "\n</ol>\n</nav>\n")
    return doc("Contents", nav)

def ncx_doc(order, uid, page_list=None):
    pts = []
    for i, (label, src) in enumerate(order, 1):
        pts.append('<navPoint id="np%d" playOrder="%d"><navLabel><text>%s</text></navLabel>'
                   '<content src="%s"/></navPoint>' % (i, i, html.escape(label), src))
    pagelist = ""
    if page_list:
        po = len(order)
        tgts = []
        for n, href in page_list:
            po += 1
            tgts.append('<pageTarget id="pt%d" type="normal" value="%d" playOrder="%d">'
                        '<navLabel><text>%d</text></navLabel><content src="%s"/></pageTarget>'
                        % (n, n, po, n, href))
        pagelist = "<pageList>\n" + "\n".join(tgts) + "\n</pageList>\n"
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
            '<head><meta name="dtb:uid" content="%s"/></head>\n'
            '<docTitle><text>Pastoral Theology</text></docTitle>\n<navMap>\n%s\n</navMap>\n%s</ncx>\n'
            ) % (uid, "\n".join(pts), pagelist)

def opf_doc(manifest, spine_ids, uid, mod):
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        '<dc:identifier id="bookid">%s</dc:identifier>\n'
        '<dc:title>Pastoral Theology: The Pastor in the Various Duties of His Office</dc:title>\n'
        '<dc:creator>Thomas Murphy</dc:creator>\n<dc:language>en</dc:language>\n'
        '<dc:date>1877</dc:date>\n<dc:publisher>Presbyterian Board of Publication</dc:publisher>\n'
        '<dc:source id="src">Internet Archive: pastoraltheology00murp (1877 print edition)</dc:source>\n'
        '<meta refines="#src" property="source-of">pagination</meta>\n'
        '<meta property="schema:accessibilityFeature">printPageNumbers</meta>\n'
        '<meta property="schema:accessibilityFeature">tableOfContents</meta>\n'
        '<meta property="dcterms:modified">%s</meta>\n<meta name="cover" content="cover-image"/>\n'
        '</metadata>\n<manifest>\n%s\n</manifest>\n<spine toc="ncx">\n%s\n</spine>\n</package>\n'
        ) % (uid, mod, "\n".join(manifest), "\n".join('<itemref idref="%s"/>' % s for s in spine_ids))

def cmd_build():
    oebps = os.path.join(BUILD, "epub", "OEBPS"); meta = os.path.join(BUILD, "epub", "META-INF")
    os.makedirs(oebps, exist_ok=True); os.makedirs(meta, exist_ok=True)
    uid = "urn:isbn:pastoraltheology00murp-1877"
    mod = datetime.datetime(2026, 7, 2, 12, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ")

    import shutil
    docs = {}
    images = []   # (id, filename, media_type, extra_props)
    # designed cover (cover.jpg in repo root) -> PNG for the EPUB
    newcover = os.path.join(BUILD, "newcover.png")
    if os.path.exists(COVER_SRC):
        from PIL import Image
        Image.open(COVER_SRC).convert("RGB").save(newcover)
    origimg = os.path.join(ASSETS, "original-title-page.png")   # facsimile of the original 1877 title page
    have_newcover = os.path.exists(newcover)
    have_orig = os.path.exists(origimg)
    if have_newcover:
        shutil.copy(newcover, os.path.join(oebps, "cover.png"))
        images.append(("cover-image", "cover.png", "image/png", ' properties="cover-image"'))
        docs["cover.xhtml"] = doc("Cover", cover_section("cover.png", "Pastoral Theology, by Thomas Murphy"))
        if have_orig:
            shutil.copy(origimg, os.path.join(oebps, "origcover.png"))
            images.append(("origcover-image", "origcover.png", "image/png", ""))
            docs["origcover.xhtml"] = origcover_doc("origcover.png")
    elif have_orig:
        shutil.copy(origimg, os.path.join(oebps, "cover.png"))
        images.append(("cover-image", "cover.png", "image/png", ' properties="cover-image"'))
        docs["cover.xhtml"] = doc("Cover", cover_section("cover.png", "Pastoral Theology, by Thomas Murphy"))
    docs["titlepage.xhtml"] = titlepage_doc()
    docs["copyright.xhtml"] = copyright_doc()
    docs["about.xhtml"] = about_doc()

    page_list = []          # (printed_number, "file#anchor") in reading order — the print page list
    page_href = {}          # printed_number -> "file#anchor" — used to link the index's page numbers
    def add_marks(fn, marks):
        for n in marks:
            href = "%s#pg%d" % (fn, n)
            page_list.append((n, href)); page_href[n] = href

    pf_doc, pf_marks = preface_doc()
    if pf_doc:
        docs["preface.xhtml"] = pf_doc; add_marks("preface.xhtml", pf_marks)

    present = []
    for roman, title, a, b in CHAPTERS:
        d, _, marks = chapter_doc(roman, title, a, b)
        if d:
            docs["ch%s.xhtml" % roman] = d; present.append(roman)
            add_marks("ch%s.xhtml" % roman, marks)

    # build the index last, so its page numbers can be linked to the body's pagebreak anchors
    ix_doc, ix_marks = index_doc(page_href)
    if ix_doc:
        docs["index.xhtml"] = ix_doc; add_marks("index.xhtml", ix_marks)

    first_content = "ch%s.xhtml" % (present[0] if present else "I")
    docs["nav.xhtml"] = nav_doc(docs, present, first_content, page_list)

    for fn, s in list(docs.items()):
        validate(s, fn)

    open(os.path.join(oebps, "style.css"), "w", encoding="utf-8").write(CSS)
    for fn, s in docs.items():
        open(os.path.join(oebps, fn), "w", encoding="utf-8").write(s)

    # spine order
    spine = []
    if "cover.xhtml" in docs: spine.append("cover.xhtml")
    if "origcover.xhtml" in docs: spine.append("origcover.xhtml")
    spine += ["titlepage.xhtml", "copyright.xhtml", "about.xhtml", "nav.xhtml"]
    if "preface.xhtml" in docs: spine.append("preface.xhtml")
    spine += ["ch%s.xhtml" % r for r, *_ in CHAPTERS if "ch%s.xhtml" % r in docs]
    if "index.xhtml" in docs: spine.append("index.xhtml")

    ncx_order = [("Title Page", "titlepage.xhtml")]
    if "origcover.xhtml" in docs: ncx_order.append(("Original Title Page", "origcover.xhtml"))
    ncx_order.append(("About This Edition", "about.xhtml"))
    if "preface.xhtml" in docs: ncx_order.append(("Preface", "preface.xhtml"))
    for roman, title, a, b in CHAPTERS:
        if "ch%s.xhtml" % roman in docs:
            ncx_order.append(("Chapter %s. %s" % (roman, title), "ch%s.xhtml" % roman))
    if "index.xhtml" in docs: ncx_order.append(("Index", "index.xhtml"))
    open(os.path.join(oebps, "toc.ncx"), "w", encoding="utf-8").write(ncx_doc(ncx_order, uid, page_list))

    def mid(fn): return re.sub(r"[^A-Za-z0-9]", "_", fn)
    manifest = []
    for fn in docs:
        prop = ' properties="nav"' if fn == "nav.xhtml" else ''
        manifest.append('<item id="%s" href="%s" media-type="application/xhtml+xml"%s/>' % (mid(fn), fn, prop))
    manifest.append('<item id="css" href="style.css" media-type="text/css"/>')
    manifest.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
    for iid, ifn, imt, iprops in images:
        manifest.append('<item id="%s" href="%s" media-type="%s"%s/>' % (iid, ifn, imt, iprops))
    open(os.path.join(oebps, "content.opf"), "w", encoding="utf-8").write(
        opf_doc(manifest, [mid(f) for f in spine], uid, mod))
    open(os.path.join(meta, "container.xml"), "w", encoding="utf-8").write(
        '<?xml version="1.0" encoding="utf-8"?>\n<container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n<rootfiles>\n'
        '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>\n'
        '</rootfiles>\n</container>\n')

    if os.path.exists(EPUB_OUT): os.remove(EPUB_OUT)
    root = os.path.join(BUILD, "epub")
    with zipfile.ZipFile(EPUB_OUT, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for base, _, files in os.walk(root):
            for f in sorted(files):
                full = os.path.join(base, f)
                z.write(full, os.path.relpath(full, root), compress_type=zipfile.ZIP_DEFLATED)
    print("Built:", EPUB_OUT)
    print("Chapters:", ",".join(present), "| docs:", len(docs), "| spine:", len(spine))
    return 0

def cmd_preview(roman):
    m = {r: (t, a, b) for r, t, a, b in CHAPTERS}
    t, a, b = m[roman]
    blocks, missing, marks = stitch_pages(range(a, b + 1))
    print("Ch %s pages %d-%d: %d blocks, missing=%s" % (roman, a, b, len(blocks), missing))
    head = ('<div class="chapnum">CHAPTER %s.</div>\n<h1 class="chaptitle">%s</h1>\n<hr class="rule"/>\n' % (roman, html.escape(t)))
    out = ('<!DOCTYPE html><html><head><meta charset="utf-8"><style>%s</style></head><body>%s\n%s</body></html>'
           % (CSS, head, "\n".join(blocks)))
    os.makedirs(BUILD, exist_ok=True)
    fp = os.path.join(BUILD, "preview_ch%s.html" % roman)
    open(fp, "w", encoding="utf-8").write(out); print("Wrote", fp)

def cmd_check():
    def span(name, pages):
        have = sum(1 for p in pages if read_page(p) is not None)
        miss = [p for p in pages if read_page(p) is None]
        print("  %-9s %3d/%3d pages%s" % (name, have, len(pages),
              ("  MISSING " + str(miss)) if miss else ""))
    span("Preface", PREFACE_PAGES)
    for roman, title, a, b in CHAPTERS:
        span("Ch " + roman, list(range(a, b + 1)))
    span("Index", INDEX_PAGES)

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "preview": cmd_preview(sys.argv[2])
    elif cmd == "build": sys.exit(cmd_build())
    else: cmd_check()
