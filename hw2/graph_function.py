import re
import sys
import time
from collections import deque



LINK_RE = re.compile(r'href="([^"]+)"', re.IGNORECASE)

def parse_links(text):
    """return all links. ex: ['123.html', '45.html', ...]"""
    return LINK_RE.findall(text)

"----------------------------------------------------------------------------------"



def show_progress(label, done, n, start):
    """one self-overwriting status line on stderr, refreshed every 1%"""
    if done % max(1, n // 100) and done != n:
        return
    elapsed = time.perf_counter() - start
    eta = elapsed / done * (n - done)
    print(f"\r{label} {done}/{n} ({done * 100 // n}%)  elapsed {elapsed:.0f}s  eta {eta:.0f}s",
          end="\n" if done == n else "", file=sys.stderr, flush=True)


def build_graph(names, read, progress=False):
    index = {name: i for i, name in enumerate(names)}
    out_adj = [None] * len(names)
    unknown = 0
    start = time.perf_counter()
    for i, name in enumerate(names):
        targets = []
        for link in parse_links(read(name)):
            j = index.get(link)
            if j is None:
                unknown += 1
            else:
                targets.append(j)
        out_adj[i] = targets
        if progress:
            show_progress("download+parse", i + 1, len(names), start)
    return out_adj, unknown


def reverse(out_adj):
    in_adj = [[] for _ in out_adj]
    for u, targets in enumerate(out_adj):
        for v in targets:
            in_adj[v].append(u)
    return in_adj


def pagerank(out_adj, in_adj, d=0.85, tol=0.005):
    """PR(A) = (1-d)/n + d * sum(PR(T)/C(T)) over pages T linking to A."""
    
    n = len(out_adj)
    out_deg = [len(targets) for targets in out_adj]
    pr = [1.0] * n
    total = float(n)
    while True:
        pr = [(1 - d) / n + d * sum(pr[t] / out_deg[t] for t in in_adj[a])
              for a in range(n)]
        new_total = sum(pr)
        if abs(new_total - total) <= tol * total:
            return pr
        total = new_total


def closeness(adj, progress=False):
    n = len(adj)
    scores = []
    start = time.perf_counter()
    for s in range(n):
        dist = [-1] * n
        dist[s] = 0
        q = deque([s])
        reached = total = 0
        while q:
            u = q.popleft()
            for v in adj[u]:
                if dist[v] < 0:
                    dist[v] = dist[u] + 1
                    reached += 1
                    total += dist[v]
                    q.append(v)
        scores.append((reached / (n - 1)) * (reached / total) if total else 0.0)
        if progress:
            show_progress("closeness", s + 1, n, start)
    return scores


def best_closeness(adj, progress=False):
    scores = closeness(adj, progress)
    best = max(range(len(scores)), key=scores.__getitem__)
    return best, scores[best]
