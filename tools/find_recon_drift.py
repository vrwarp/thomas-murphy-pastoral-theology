#!/usr/bin/env python3
"""Detect reconstruction-vs-OCR drift.

Reconstruction (ocr_reconstruct.py) re-OCRs each page via `run_tsv` to get word
geometry, and uses that pass's TEXT. That text can differ from the plain-text OCR
in artifacts/ocr/ — the pass the proofreading agents actually validated against
the page image. Where the reconstructed section contains a (rare, non-dictionary)
word that the validated plain OCR reads as a common word, the reconstruction has
almost certainly drifted (e.g. "thimgs" for "things"). Emits per-page hint files
for image validation via wf_validate_typos.js, identical in shape to
find_typo_suspects.py output — nothing is auto-applied.

Usage: python3 tools/find_recon_drift.py   # writes work/drift-suspects.json + hints
"""
import os, re, glob, json, difflib
from collections import Counter

ROOT = os.environ.get("PT_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEC = os.path.join(ROOT, "artifacts", "sections")
OCRD = os.path.join(ROOT, "artifacts", "ocr")
OUTJ = os.path.join(ROOT, "work", "drift-suspects.json")
HINTS = os.path.join(ROOT, "work", "typo-hints")

def sec_text(pg):
    t = open(os.path.join(SEC, "sec_p%03d.html" % pg), encoding="utf-8").read()
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)

def ocr_text(pg):
    lines = open(os.path.join(OCRD, "p%03d.txt" % pg), encoding="utf-8").read().splitlines()
    return " ".join(lines[1:])          # drop the running-head line

def toks(s):
    return [w.lower() for w in re.findall(r"[A-Za-z]+", s)]

def load_dict():
    try:
        return set(w.strip().lower() for w in open("/usr/share/dict/words"))
    except OSError:
        return set()

def main():
    dictionary = load_dict()
    # book-wide frequency of every word as OCR'd, to know which corrections are "to a common word"
    ocr_freq = Counter()
    ocr_by_page = {}
    for f in glob.glob(os.path.join(OCRD, "p*.txt")):
        pg = int(re.search(r"p(\d+)", f).group(1))
        tk = toks(ocr_text(pg))
        ocr_by_page[pg] = Counter(tk)
        ocr_freq.update(tk)

    suspects = []
    for sf in sorted(glob.glob(os.path.join(SEC, "sec_p*.html"))):
        pg = int(re.search(r"p(\d+)", sf).group(1))
        if pg not in ocr_by_page:
            continue
        sc = Counter(toks(sec_text(pg)))
        oc = ocr_by_page[pg]
        sec_only = [w for w in sc if sc[w] > oc.get(w, 0)]        # words the section added
        ocr_only = [w for w in oc if oc[w] > sc.get(w, 0)]        # words only the OCR has
        for s in sec_only:
            if len(s) < 4 or s in dictionary or ocr_freq.get(s, 0) > 2:
                continue                                          # skip real/common words
            best = None
            for o in ocr_only:
                if abs(len(o) - len(s)) > 2 or o == s:
                    continue
                r = difflib.SequenceMatcher(None, s, o).ratio()
                # correct only toward a word that is common in the book (a confident target)
                if r >= 0.8 and ocr_freq.get(o, 0) >= 8 and (best is None or r > best[1]):
                    best = (o, r)
            if best:
                suspects.append({"page": pg, "wrong": s, "suggested": best[0],
                                 "ratio": round(best[1], 3), "target_freq": ocr_freq.get(best[0], 0)})

    by_page = {}
    for s in suspects:
        by_page.setdefault(s["page"], []).append(s)
    json.dump({"suspects": suspects}, open(OUTJ, "w"), indent=1)

    # write/extend per-page hint files (reuse the wf_validate_typos.js format)
    os.makedirs(HINTS, exist_ok=True)
    for pg, items in by_page.items():
        hp = os.path.join(HINTS, "hints_p%03d.json" % pg)
        existing = json.load(open(hp))["suspects"] if os.path.exists(hp) else []
        have = {(h.get("text_token","").lower(), h.get("suggested","")) for h in existing}
        txt = sec_text(pg)
        for it in items:
            if (it["wrong"], it["suggested"]) in have:
                continue
            m = re.search(r"(?<![A-Za-z])(%s)(?![A-Za-z])" % re.escape(it["wrong"]), txt, re.I)
            ctx = txt[max(0, m.start()-45):m.end()+45].strip() if m else ""
            existing.append({"text_token": it["wrong"], "suggested": it["suggested"], "context": ctx})
        json.dump({"page": pg, "suspects": existing}, open(hp, "w"), indent=1)

    print("drift suspects: %d across %d pages" % (len(suspects), len(by_page)))
    for s in sorted(suspects, key=lambda x: -x["target_freq"]):
        print("  p%03d  %-16s -> %-16s  ratio=%.2f  (target x%d)"
              % (s["page"], s["wrong"], s["suggested"], s["ratio"], s["target_freq"]))
    print("\npages to validate:", sorted(by_page))

if __name__ == "__main__":
    main()
