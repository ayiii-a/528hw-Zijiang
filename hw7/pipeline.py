"""HW7: link and trigram statistics of the HW2 pages with Apache Beam.

From the HTML files in gs://528-zz-hw2/pages/ the pipeline finds the 5 files with the most incoming
links, the 5 files with the most outgoing links and the 5 most frequent word trigrams. It writes them
to --output and prints them, with the run time, once the pipeline has finished. The same code runs
on the laptop (DirectRunner) and on Cloud Dataflow (DataflowRunner); see README.md.
"""
import argparse
import functools
import os
import re
import time
from collections import Counter

import apache_beam as beam
from apache_beam.io import fileio
from apache_beam.io.filesystems import FileSystems
from apache_beam.options.pipeline_options import PipelineOptions, SetupOptions, StandardOptions

LINK_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)     # the same pattern as HW2
TAG_RE = re.compile(r"<[^>]+>")
WORD_RE = re.compile(r"[a-z0-9]+")
TOP = 5
RESULTS = [("top_incoming", "Top 5 files with the most incoming links"),
           ("top_outgoing", "Top 5 files with the most outgoing links"),
           ("top_trigrams", "Top 5 most frequent word trigrams")]


def read_page(readable_file):
    """(file name, HTML text); gs://528-zz-hw2/pages/12.html -> 12.html, the way links name pages
    (os.path.basename splits local Windows paths at both kinds of slash)"""
    return os.path.basename(readable_file.metadata.path), readable_file.read_utf8()


def links(text):
    """Every link of a page, duplicates included (as in HW2): ['6890.html', '663.html', ...]"""
    return LINK_RE.findall(text)


def trigram_counts(text):
    """Counts of the consecutive word triplets of one page. Words are runs of letters and digits of
    the visible text: tags are removed and everything is lower case. Counting inside each page first
    turns about 140 million trigrams into a few dozen (trigram, count) pairs per page."""
    words = WORD_RE.findall(TAG_RE.sub(" ", text).lower())
    return [(" ".join(t), n) for t, n in Counter(zip(words, words[1:], words[2:])).items()]


@functools.total_ordering
class Desc:
    """Reverses the order of a value, so that among equal counts Top keeps the smallest name."""
    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        return self.value == other.value

    def __lt__(self, other):
        return self.value > other.value


def rank_key(item):
    """Highest count first; equal counts by page number (12.html before 100.html), then alphabetically."""
    name, count = item
    stem = name.split(".")[0]
    return count, Desc((0, int(stem), "") if stem.isdigit() else (1, 0, name))


def format_result(top, title, tied):
    lines = [title] + [f"  {i}. {name:<30} {count:>12,}" for i, (name, count) in enumerate(top, 1)]
    if top and tied > 1:
        lines.append(f"  ({tied:,} entries share the count of the 5th place, {top[-1][1]:,}; "
                     "equal counts are ordered by page number or alphabetically)")
    return "\n".join(lines)


def top_with_ties(counts, name, title, output):
    """Writes the top 5 of (name, count) pairs, and how many share the count of the 5th, to output."""
    top = counts | f"Top {name}" >> beam.combiners.Top.Of(TOP, key=rank_key)
    tied = (counts
            | f"Tied {name}" >> beam.Filter(lambda kv, top: bool(top) and kv[1] == top[-1][1],
                                            top=beam.pvalue.AsSingleton(top))
            | f"CountTied {name}" >> beam.combiners.Count.Globally())
    return (top
            | f"Format {name}" >> beam.Map(format_result, title, tied=beam.pvalue.AsSingleton(tied))
            | f"Write {name}" >> beam.io.WriteToText(f"{output}/{name}", file_name_suffix=".txt",
                                                     shard_name_template=""))


def run(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="gs://528-zz-hw2/pages/*.html", help="files to read (glob)")
    parser.add_argument("--output", help="where to write the results "
                                         "(default: gs://528-zz-hw2/hw7/output/<runner>)")
    args, beam_args = parser.parse_known_args(argv)
    options = PipelineOptions(beam_args)
    options.view_as(SetupOptions).save_main_session = True     # module imports for Dataflow workers
    runner = options.view_as(StandardOptions).runner or "DirectRunner"
    output = (args.output or f"gs://528-zz-hw2/hw7/output/{runner}").rstrip("/")

    started = time.perf_counter()
    with beam.Pipeline(options=options) as p:                   # runs and waits at the end of the block
        pages = (p
                 | "MatchFiles" >> fileio.MatchFiles(args.input,     # fail if no file matches
                                                   empty_match_treatment=fileio.EmptyMatchTreatment.DISALLOW)
                 | "Spread" >> beam.Reshuffle()                 # distribute the files over the workers
                 | "ReadMatches" >> fileio.ReadMatches()
                 | "ReadPages" >> beam.Map(read_page))
        incoming = (pages
                    | "Links" >> beam.FlatMap(lambda page: links(page[1]))
                    | "CountIncoming" >> beam.combiners.Count.PerElement())
        outgoing = pages | "CountOutgoing" >> beam.Map(lambda page: (page[0], len(links(page[1]))))
        trigrams = (pages
                    | "TrigramsPerPage" >> beam.FlatMap(lambda page: trigram_counts(page[1]))
                    | "SumTrigrams" >> beam.CombinePerKey(sum))
        for (name, title), counts in zip(RESULTS, [incoming, outgoing, trigrams]):
            top_with_ties(counts, name, title, output)
    elapsed = time.perf_counter() - started

    print(f"\nResults of {runner} on {args.input}, written to {output}/\n")
    for name, _ in RESULTS:
        with FileSystems.open(f"{output}/{name}.txt") as f:
            print(f.read().decode("utf-8"))
    print(f"Run time ({runner}, from start to the end of the pipeline): {elapsed:.1f} s")


if __name__ == "__main__":
    run()
