#!/usr/bin/env python3
"""Measure the readability of a BPMN diagram's DI layout.

Reports, per diagram:
  through  - edge segments passing through a shape that is not one of the
             edge's own endpoints (or the host of a boundary-event source)
  overlap  - pairs of segments from different edges lying on the same line
             with overlapping extent (drawn on top of each other)
  cross    - perpendicular crossings between segments of different edges
  covered  - enhanced elements whose bottom-right / top-right badge corner is
             covered by a boundary event

Exit status 1 if `through` or `overlap` is non-zero (use --max-cross N to
also gate crossings).

Usage:  python tools/check_layout.py FILE.bpmn [--verbose]
"""
import argparse
import sys
from itertools import combinations

from lxml import etree

BPMN = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
BPMNDI = 'http://www.omg.org/spec/BPMN/20100524/DI'
DC = 'http://www.omg.org/spec/DD/20100524/DC'
DI = 'http://www.omg.org/spec/DD/20100524/DI'
CONTAINER = {'participant', 'lane'}


def load(path):
    root = etree.parse(path).getroot()
    elems = {e.get('id'): e for e in root.iter() if isinstance(e.tag, str) and e.get('id')}
    shapes, edges = {}, {}
    for s in root.iter(f'{{{BPMNDI}}}BPMNShape'):
        b = s.find(f'{{{DC}}}Bounds')
        el = elems.get(s.get('bpmnElement'))
        if b is None or el is None or etree.QName(el).localname in CONTAINER:
            continue
        shapes[s.get('bpmnElement')] = tuple(float(b.get(k)) for k in ('x', 'y', 'width', 'height'))
    for e in root.iter(f'{{{BPMNDI}}}BPMNEdge'):
        pts = [(float(w.get('x')), float(w.get('y'))) for w in e.iter(f'{{{DI}}}waypoint')]
        el = elems.get(e.get('bpmnElement'))
        if el is not None and len(pts) >= 2:
            edges[e.get('bpmnElement')] = (el.get('sourceRef'), el.get('targetRef'), pts)
    attached = {i: e.get('attachedToRef') for i, e in elems.items()
                if etree.QName(e).localname == 'boundaryEvent'}
    enhanced = {i for i, e in elems.items()
                if e.find(f'{{{BPMN}}}extensionElements') is not None
                and any(etree.QName(c).localname == 'enhancement'
                        for c in e.find(f'{{{BPMN}}}extensionElements'))}
    return shapes, edges, attached, enhanced


def segments(pts):
    return list(zip(pts, pts[1:]))


def check(path, verbose=False):
    shapes, edges, attached, enhanced = load(path)
    through, overlap, cross, covered = [], [], [], []
    for fid, (s, t, pts) in edges.items():
        skip = {s, t, attached.get(s), attached.get(t)}
        for (ax, ay), (bx, by) in segments(pts):
            lx, hx = sorted((ax, bx)); ly, hy = sorted((ay, by))
            for k, (x, y, w, h) in shapes.items():
                if k in skip or attached.get(k) in (s, t):
                    continue
                if lx < x + w - 2 and hx > x + 2 and ly < y + h - 2 and hy > y + 2:
                    through.append((fid, k))
    for (f1, (_, _, p1)), (f2, (_, _, p2)) in combinations(edges.items(), 2):
        for (a, b) in segments(p1):
            for (c, d) in segments(p2):
                v1, v2 = abs(a[0] - b[0]) < 0.5, abs(c[0] - d[0]) < 0.5
                h1, h2 = abs(a[1] - b[1]) < 0.5, abs(c[1] - d[1]) < 0.5
                if v1 and v2 and abs(a[0] - c[0]) < 0.5:
                    o = min(max(a[1], b[1]), max(c[1], d[1])) - max(min(a[1], b[1]), min(c[1], d[1]))
                    if o > 2:
                        overlap.append((f1, f2, round(o)))
                elif h1 and h2 and abs(a[1] - c[1]) < 0.5:
                    o = min(max(a[0], b[0]), max(c[0], d[0])) - max(min(a[0], b[0]), min(c[0], d[0]))
                    if o > 2:
                        overlap.append((f1, f2, round(o)))
                elif (v1 and h2) or (h1 and v2):
                    (vx, vy0, vy1), (hy, hx0, hx1) = ((a[0], *sorted((a[1], b[1]))), (c[1], *sorted((c[0], d[0])))) \
                        if v1 else ((c[0], *sorted((c[1], d[1]))), (a[1], *sorted((a[0], b[0]))))
                    if hx0 + 1 < vx < hx1 - 1 and vy0 + 1 < hy < vy1 - 1:
                        cross.append((f1, f2))
    for b, host in attached.items():
        if host in enhanced and b in shapes and host in shapes:
            x, y, w, h = shapes[host]
            bx, by, bw, bh = shapes[b]
            if bx < x + w - 3 < bx + bw and by < y + h - 3 < by + bh:
                covered.append((host, b))
    return dict(through=through, overlap=overlap, cross=cross, covered=covered)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('files', nargs='+')
    ap.add_argument('--verbose', '-v', action='store_true')
    ap.add_argument('--max-cross', type=int, default=None)
    a = ap.parse_args(argv)
    bad = False
    for f in a.files:
        r = check(f, a.verbose)
        print(f'{f}: through={len(r["through"])} overlap={len(r["overlap"])} '
              f'cross={len(r["cross"])} covered={len(r["covered"])}')
        if a.verbose:
            for k in ('through', 'overlap', 'cross', 'covered'):
                for item in r[k]:
                    print(f'  {k}: {item}')
        if r['through'] or r['overlap'] or (a.max_cross is not None and len(r['cross']) > a.max_cross):
            bad = True
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
