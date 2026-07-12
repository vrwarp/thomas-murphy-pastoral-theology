#!/usr/bin/env python3
"""Merge AI-confirmed typo fixes (work/typo-confirmed/confirmed_p<NNN>.json)
into the per-page deltas (artifacts/deltas/delta_p<NNN>.json).

Safety: delta "fixes" are applied with plain substring replacement, so each
confirmed token is converted into a replacement string that cannot corrupt
other words. If the token's substring count on the page equals its
word-boundary count, the bare token is safe; otherwise the fix is expanded
with surrounding context words until the snippet is unique.

Usage: python3 tools/merge_confirmed_fixes.py    # prints a per-fix report
"""
import os, re, glob, json

ROOT = os.environ.get("PT_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(ROOT, "work", "typo-confirmed")
DELTAS = os.path.join(ROOT, "artifacts", "deltas")
SECTIONS = os.path.join(ROOT, "artifacts", "sections")

def stripped(pg):
    t = open(os.path.join(SECTIONS, "sec_p%03d.html" % pg), encoding="utf-8").read()
    t = re.sub(r"<!--.*?-->", " ", t, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)

def safe_fixes(pg, wrong, right):
    """Return a list of {wrong,right} plain-replacement pairs that are word-boundary safe."""
    txt = stripped(pg)
    wb = list(re.finditer(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(wrong), txt))
    if not wb:
        return None                      # token not present (already fixed?)
    if txt.count(wrong) == len(wb):
        return [{"wrong": wrong, "right": right}]          # bare token is unambiguous
    out = []
    for m in wb:                          # embedded elsewhere: expand with context
        for pad in (12, 25, 45):
            a, b = max(0, m.start() - pad), min(len(txt), m.end() + pad)
            snip = txt[a:b]
            if txt.count(snip) == 1:
                out.append({"wrong": snip, "right": snip.replace(wrong, right)})
                break
        else:
            return None                   # could not build a unique snippet
    return out

def main():
    merged, skipped = 0, []
    for f in sorted(glob.glob(os.path.join(CONF, "confirmed_p*.json"))):
        d = json.load(open(f))
        pg = d["page"]
        fixes = d.get("confirmed", [])
        if not fixes:
            continue
        dp = os.path.join(DELTAS, "delta_p%03d.json" % pg)
        delta = json.load(open(dp))
        existing = {(x.get("wrong"), x.get("right")) for x in delta.get("fixes", [])}
        for fx in fixes:
            if fx["wrong"] == fx["right"]:
                continue
            safe = safe_fixes(pg, fx["wrong"], fx["right"])
            if safe is None:
                skipped.append((pg, fx["wrong"], fx["right"]))
                continue
            for s in safe:
                if (s["wrong"], s["right"]) not in existing:
                    delta.setdefault("fixes", []).append(s)
                    existing.add((s["wrong"], s["right"]))
                    merged += 1
                    print("p%03d: %r -> %r" % (pg, s["wrong"], s["right"]))
        json.dump(delta, open(dp, "w", encoding="utf-8"), indent=1)
    print("\nmerged %d fixes into deltas | skipped: %s" % (merged, skipped or "none"))

if __name__ == "__main__":
    main()
