"""Local check of pipeline.py: runs it with the DirectRunner on a folder of pages and compares its
results with a plain Python computation of the same numbers.
    python test_pipeline.py DIR_WITH_HTML_FILES"""
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

import pipeline

pages = {p.name: p.read_text(encoding="utf-8") for p in Path(sys.argv[1]).glob("*.html")}
link_re = re.compile(r'href="([^"]+)"', re.IGNORECASE)
incoming = Counter(link for text in pages.values() for link in link_re.findall(text))
outgoing = {name: len(link_re.findall(text)) for name, text in pages.items()}
trigrams = Counter()
for text in pages.values():
    words = re.findall(r"[a-z0-9]+", re.sub(r"<[^>]+>", " ", text).lower())
    trigrams.update(" ".join(words[i:i + 3]) for i in range(len(words) - 2))


def expected_top(counts, numeric):
    order = sorted(counts.items(), key=lambda kv: (-kv[1], int(kv[0].split(".")[0]) if numeric else kv[0]))
    return [(name, n) for name, n in order[:5]], sum(n == order[4][1] for n in counts.values())


out = tempfile.mkdtemp()
pipeline.run(["--input", str(Path(sys.argv[1]) / "*.html"), "--output", out, "--runner", "DirectRunner"])
for (name, _), counts, numeric in zip(pipeline.RESULTS, [incoming, outgoing, trigrams], [True, True, False]):
    lines = Path(out, f"{name}.txt").read_text(encoding="utf-8").splitlines()
    got = [(m.group(1), int(m.group(2).replace(",", ""))) for m in
           (re.match(r"\s+\d\. (.+?)\s+([\d,]+)$", line) for line in lines[1:6])]
    top, tied = expected_top(counts, numeric)
    assert got == top, (name, got, top)
    if tied > 1:
        assert f"({tied:,} entries share" in lines[-1], (name, lines[-1], tied)
print(f"all checks passed on {len(pages)} pages")
