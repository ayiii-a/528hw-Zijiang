from pytest import approx

from graph_function import build_graph, reverse, pagerank, closeness, best_closeness


def graph(pages):
    names = sorted(pages)
    return build_graph(names, lambda name: pages[name])


def test_simple_cycle():
    # 0 -> 1,2 ; 1 -> 2 ; 2 -> 0
    out_adj, unknown = graph({
        "0.html": '<a HREF="1.html">x</a> <a HREF="2.html">x</a>',
        "1.html": '<a HREF="2.html">x</a>',
        "2.html": '<a HREF="0.html">x</a>',
    })
    assert out_adj == [[1, 2], [2], [0]]
    assert unknown == 0
    assert reverse(out_adj) == [[2], [0], [0, 1]]


def test_edge_cases():
    # unknown links, duplicate link, self-loop, page with no out-links
    out_adj, unknown = graph({
        "0.html": '<a HREF="1.html">x</a> <a href="1.html">x</a> <a HREF="99.html">x</a>',
        "1.html": '<a HREF="1.html">x</a> <a HREF="missing.html">x</a>',
        "2.html": 'no links here',
    })
    assert out_adj == [[1, 1], [1], []]   # duplicates and self-loops are kept
    assert unknown == 2
    assert reverse(out_adj) == [[], [0, 0, 1], []]


def test_star():
    # every page points to 0, 0 points to nobody
    out_adj, unknown = graph({
        "0.html": '',
        "1.html": '<a HREF="0.html">x</a>',
        "2.html": '<a HREF="0.html">x</a>',
        "3.html": '<a HREF="0.html">x</a>',
    })
    assert out_adj == [[], [0], [0], [0]]
    assert unknown == 0
    assert reverse(out_adj) == [[1, 2, 3], [], [], []]


def pr_of(out_adj):
    return pagerank(out_adj, reverse(out_adj))


# ---------- PageRank ----------

# Start at PR=1 per page. Without dangling nodes the total goes S_k = 1 + 0.85^k (n-1),
# and "total changes <= 0.5%" stops once S <= 1 + 0.85/29 ~ 1.029,
# so results sit up to ~3% above the true fixed point.

def test_pagerank_cycle():
    # symmetric 4-cycle: all pages equal, x_k = 0.25 + 0.75 * 0.85^k.
    # stop when 0.45*0.85^(k-1) <= 0.005*(1 + 3*0.85^(k-1))  ->  k = 29
    assert pr_of([[1], [2], [3], [0]]) == approx([0.25 + 0.75 * 0.85 ** 29] * 4)


def test_pagerank_hand_computed():
    # A->B, A->C, B->C, C->A, D->C (A..D = 0..3). Fixed point by hand:
    # D = .0375 (nobody links to D)
    # B = .0375 + .425A ;  C = .0375 + .85(A/2 + B + D) = .10125 + .78625A
    # A = .0375 + .85C  ->  .3316875A = .1235625  ->  A = .372527
    fixed = [0.372527, 0.195824, 0.394149, 0.0375]
    assert pr_of([[1, 2], [2], [0], [2]]) == approx(fixed, rel=0.03)


def test_pagerank_sum_without_dangling():
    for out_adj in ([[1], [2], [3], [0]],
                    [[1, 2], [2], [0], [2]],
                    [[1, 2], [0, 2], [0, 1]],   # complete graph
                    [[0, 1], [0]]):             # self-loop
        assert 1 < sum(pr_of(out_adj)) <= 1 + 0.85 / 29


def test_pagerank_star_center_highest():
    # leaves 1..4 all link to center 0
    pr = pr_of([[], [0], [0], [0], [0]])
    assert max(range(5), key=pr.__getitem__) == 0
    assert all(pr[0] > pr[i] for i in range(1, 5))


def test_pagerank_single_node():
    assert pr_of([[]]) == approx([0.15])    # dangling: 1 -> .15 -> .15, stop
    assert pr_of([[0]]) == approx([1.0])    # self-loop keeps all the rank


def test_pagerank_self_loop():
    # 0 -> 0, 0 -> 1, 1 -> 0. Fixed point: PR1 = .075 + .425 PR0,
    # PR0 = .075 + .85(PR0/2 + PR1)  ->  PR0 = 37/57, PR1 = 20/57
    assert pr_of([[0, 1], [0]]) == approx([37 / 57, 20 / 57], rel=0.03)


def test_pagerank_dangling():
    # 0 -> 1, page 1 has no out-links (hand-computed: sums 2 -> 1 -> 0.21375 -> 0.21375)
    assert pr_of([[1], []]) == approx([0.075, 0.13875])


# ---------- Closeness ----------
# score = (r/(n-1)) * (r/total_dist), r = #nodes reachable from u, unreachable ones skipped

def test_closeness_chain():
    # 0 -> 1 -> 2 -> 3
    # 0: r=3, dist 1+2+3=6 -> 1   * 3/6 = 1/2
    # 1: r=2, dist 1+2=3   -> 2/3 * 2/3 = 4/9
    # 2: r=1, dist 1       -> 1/3 * 1   = 1/3
    # 3: reaches nobody    -> 0
    out_adj = [[1], [2], [3], []]
    assert closeness(out_adj) == approx([1 / 2, 4 / 9, 1 / 3, 0])
    assert best_closeness(out_adj) == (0, approx(1 / 2))


def test_closeness_complete_graph():
    n = 5
    out_adj = [[v for v in range(n) if v != u] for u in range(n)]
    assert closeness(out_adj) == approx([1.0] * n)


def test_closeness_star():
    # center 0 <-> leaves 1..4
    # center: dist 1 to all 4 -> 1 ; leaf: 1 to center + 2 to each of 3 leaves = 7 -> 4/7
    out_adj = [[1, 2, 3, 4], [0], [0], [0], [0]]
    assert closeness(out_adj) == approx([1.0] + [4 / 7] * 4)
    assert best_closeness(out_adj)[0] == 0


def test_closeness_unreachable():
    # 0 -> 1 and 2 -> 3 -> 4, two separate pieces, n=5
    # 0: r=1, dist 1 -> 1/4 * 1   = 1/4   (short distance, but reaches only 1 of 4)
    # 2: r=2, dist 3 -> 2/4 * 2/3 = 1/3   <- best: reaching more nodes wins
    # 3: r=1, dist 1 -> 1/4
    # 1, 4: reach nobody -> 0
    out_adj = [[1], [], [3], [4], []]
    assert closeness(out_adj) == approx([1 / 4, 0, 1 / 3, 1 / 4, 0])
    assert best_closeness(out_adj) == (2, approx(1 / 3))


def test_closeness_star_incoming():
    # everyone links to 0: by incoming distance, 0 is reached by all at distance 1
    out_adj = [[], [0], [0], [0]]
    assert best_closeness(reverse(out_adj)) == (0, 1.0)
