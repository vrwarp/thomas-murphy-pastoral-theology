#!/usr/bin/env python3
"""Find likely OCR typos in the reconstructed text and emit per-page hints for
AI validation against the page images.

Strategy — intra-corpus confusion-pair frequency analysis:
Tesseract misreads of worn 19th-century type follow known letter-confusion
patterns (e<->c, rn<->m, li<->h, u<->n, ...). A genuine misread is therefore a
token that is (a) RARE in this book, while (b) some confusion-variant of it is
COMMON in this book. "prayer-mect" is flagged because "mect" occurs twice while
"meet" occurs dozens of times, and ec->ee is a known confusion. Corpus frequency
is the primary signal (it adapts to the book's own vocabulary, archaic spellings
included); a dictionary with naive inflection handling is a secondary signal.
The output is NOT applied automatically — it is a hint list for per-page agents
to validate against the page image (the authority), like the original delta pass.

Usage:
  python3 tools/find_typo_suspects.py            # writes work/typo-suspects.json, prints summary
"""
import os, re, glob, json
from collections import Counter, defaultdict

ROOT = os.environ.get("PT_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECTIONS = os.path.join(ROOT, "artifacts", "sections")
OUT = os.path.join(ROOT, "work", "typo-suspects.json")

# OCR confusion substitutions (applied in the direction typo -> correct).
CONFUSIONS = [
    ("c", "e"), ("e", "c"),          # mect->meet, saered? (e->c also: "cvery"->"every")
    ("c", "o"), ("o", "c"),
    ("u", "n"), ("n", "u"),          # aud->and
    ("u", "h"), ("h", "u"),          # Tuat->That
    ("b", "h"), ("h", "b"),          # bave->have
    ("li", "h"), ("h", "li"),        # wliich->which
    ("rn", "m"), ("m", "rn"),        # modem->modern
    ("in", "m"), ("m", "in"),
    ("vv", "w"),
    ("f", "t"), ("t", "f"),          # of->ot
    ("l", "i"), ("i", "l"),
    ("j", "i"),
    ("ff", "fl"), ("fl", "ff"),
    ("cl", "d"), ("d", "cl"),
]

def page_text(path):
    t = open(path, encoding="utf-8").read()
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = t.replace("&amp;", "&").replace("&lt;", "<")
    return t

def load_dictionary():
    words = set()
    try:
        for w in open("/usr/share/dict/words"):
            words.add(w.strip().lower())
    except OSError:
        return None
    # naive inflection expansion so plurals/participles count as words
    base = list(words)
    for w in base:
        words.add(w + "s")
        words.add(w + "es")
        if w.endswith("e"):
            words.add(w + "d");  words.add(w[:-1] + "ing")
        else:
            words.add(w + "ed"); words.add(w + "ing")
        if w.endswith("y"):
            words.add(w[:-1] + "ies")
    return words

def variants(tok):
    out = set()
    for a, b in CONFUSIONS:
        start = 0
        while True:
            i = tok.find(a, start)
            if i < 0:
                break
            out.add(tok[:i] + b + tok[i + len(a):])
            start = i + 1
    return out - {tok}

def main():
    pages = {}
    for f in sorted(glob.glob(os.path.join(SECTIONS, "sec_p*.html"))):
        pg = int(re.search(r"sec_p(\d+)\.html", f).group(1))
        pages[pg] = page_text(f)

    freq = Counter()
    tok_pages = defaultdict(set)
    for pg, txt in pages.items():
        for tok in re.findall(r"[A-Za-z]+", txt):
            low = tok.lower()
            freq[low] += 1
            tok_pages[low].add(pg)

    dictionary = load_dictionary() or set()

    suspects = []
    for tok, f_tok in freq.items():
        if len(tok) < 4 or f_tok > 3:
            continue
        best = None
        for v in variants(tok):
            f_v = freq.get(v, 0)
            if f_v < 5 or f_v < 5 * f_tok:
                continue
            # a dictionary word (e.g. "arc") needs overwhelming evidence to be
            # treated as a typo for its variant ("are"); a non-word needs less
            need = 100 * f_tok if tok in dictionary else 5 * f_tok
            if f_v >= max(5, need) and (best is None or f_v > best[1]):
                best = (v, f_v)
        if best:
            suspects.append({
                "wrong": tok, "right": best[0],
                "wrong_freq": f_tok, "right_freq": best[1],
                "pages": sorted(tok_pages[tok]),
                "in_dict": tok in dictionary,
            })

    suspects.sort(key=lambda s: -s["right_freq"] / max(1, s["wrong_freq"]))

    # group per page for the validation agents
    by_page = defaultdict(list)
    for s in suspects:
        for pg in s["pages"]:
            by_page[pg].append({"wrong": s["wrong"], "suggested": s["right"]})

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump({"suspects": suspects, "by_page": {str(k): v for k, v in sorted(by_page.items())}},
              open(OUT, "w", encoding="utf-8"), indent=1)

    print("tokens: %d distinct | suspects: %d | pages with suspects: %d"
          % (len(freq), len(suspects), len(by_page)))
    for s in suspects[:40]:
        print("  %-16s -> %-16s %3dx vs %4dx  pages %s%s"
              % (s["wrong"], s["right"], s["wrong_freq"], s["right_freq"],
                 s["pages"][:6], " [dictword]" if s["in_dict"] else ""))

if __name__ == "__main__":
    main()
