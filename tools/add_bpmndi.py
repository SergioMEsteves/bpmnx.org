#!/usr/bin/env python3
"""Generate BPMNDI (diagram interchange) for a BPMN/BPMNx file that lacks it.

Simple deterministic layered layout: each flow node goes in a column by its
longest-path depth from the process's start nodes; each lane (or each process
without lanes) is a horizontal band; pools stack vertically. Boundary events
sit on the bottom edge of their host. Message flows are drawn as straight
vertical-ish connectors. The output opens in bpmn.io / Camunda Modeler / the
BPMNx Bench; hand-tune positions there if you want a prettier diagram.

Any existing <bpmndi:BPMNDiagram> is replaced.

Usage:
  python tools/add_bpmndi.py FILE.bpmn [--in-place]
"""
import argparse
import sys
from collections import defaultdict

from lxml import etree

BPMN = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
BPMNDI = 'http://www.omg.org/spec/BPMN/20100524/DI'
DC = 'http://www.omg.org/spec/DD/20100524/DC'
DI = 'http://www.omg.org/spec/DD/20100524/DI'

SIZE = {'event': (36, 36), 'gateway': (50, 50), 'task': (110, 80)}
COL_W, ROW_H, POOL_HDR, LANE_HDR, PAD_X, BAND_PAD = 170, 120, 30, 30, 40, 20
FLOW = {'task', 'serviceTask', 'userTask', 'businessRuleTask', 'scriptTask', 'sendTask',
        'receiveTask', 'manualTask', 'callActivity', 'subProcess', 'transaction', 'adHocSubProcess',
        'exclusiveGateway', 'inclusiveGateway', 'parallelGateway', 'eventBasedGateway', 'complexGateway',
        'startEvent', 'endEvent', 'intermediateCatchEvent', 'intermediateThrowEvent', 'boundaryEvent'}


def q(ns, local):
    return f'{{{ns}}}{local}'


def kind(local):
    if local.endswith('Event'):
        return 'event'
    if local.endswith('Gateway'):
        return 'gateway'
    return 'task'


def layout_process(proc):
    """Return {id: (col, band_key, local)}, ordered band keys, attached boundary map."""
    nodes = {n.get('id'): n for n in proc if isinstance(n.tag, str)
             and etree.QName(n).localname in FLOW}
    boundary = {i: n.get('attachedToRef') for i, n in nodes.items()
                if etree.QName(n).localname == 'boundaryEvent'}
    succ = defaultdict(list)
    indeg = defaultdict(int)
    for f in proc.iter(q(BPMN, 'sequenceFlow')):
        s, t = f.get('sourceRef'), f.get('targetRef')
        if s in nodes and t in nodes:
            succ[s].append(t)
            indeg[t] += 1
    # longest-path depth by bounded relaxation; a boundary event shares its
    # host's column (weight-0 edge), everything else is one column on
    # drop back-edges (loops such as "return for rework") so they don't push
    # the whole downstream graph to the right; found by DFS from the sources
    back, state = set(), {}
    kids = defaultdict(list)
    for u in succ:
        kids[u].extend(succ[u])
    for b, h in boundary.items():
        if h in nodes:
            kids[h].append(b)

    def dfs(root):
        stack = [(root, iter(kids[root]))]
        state[root] = 1
        while stack:
            u, it = stack[-1]
            v = next(it, None)
            if v is None:
                state[u] = 2
                stack.pop()
            elif state.get(v) == 1:
                back.add((u, v))
            elif v not in state:
                state[v] = 1
                stack.append((v, iter(kids[v])))

    for n in [n for n in nodes if indeg[n] == 0 and n not in boundary] + list(nodes):
        if n not in state:
            dfs(n)
    edges = [(u, v, 1) for u in succ for v in succ[u] if (u, v) not in back] + \
            [(h, b, 0) for b, h in boundary.items() if h in nodes]
    depth = {n: 0 for n in nodes}
    for _ in range(len(nodes)):
        changed = False
        for u, v, w in edges:
            if depth[u] + w > depth[v] and depth[u] + w <= len(nodes):
                depth[v] = depth[u] + w
                changed = True
        if not changed:
            break

    # lanes (innermost wins)
    lane_of = {}
    lanes = []

    def walk(ls, d):
        for lane in ls.findall(q(BPMN, 'lane')):
            lanes.append((lane.get('id'), d, lane))
            for r in lane.findall(q(BPMN, 'flowNodeRef')):
                lane_of[(r.text or '').strip()] = lane.get('id')
            for c in lane.findall(q(BPMN, 'childLaneSet')):
                walk(c, d + 1)

    for ls in proc.findall(q(BPMN, 'laneSet')):
        walk(ls, 0)
    leaf_lanes = [lid for lid, d, el in lanes if el.find(q(BPMN, 'childLaneSet')) is None]
    bands = leaf_lanes or [None]
    for b, host in boundary.items():
        lane_of[b] = lane_of.get(host)
    placed = {n: (depth[n], lane_of.get(n) if leaf_lanes else None,
                  etree.QName(nodes[n]).localname) for n in nodes}
    return placed, bands, boundary, lanes


def build(root):
    for d in root.findall(q(BPMNDI, 'BPMNDiagram')):
        root.remove(d)
    collab = root.find(q(BPMN, 'collaboration'))
    procs = {p.get('id'): p for p in root.findall(q(BPMN, 'process'))}
    parts = collab.findall(q(BPMN, 'participant')) if collab is not None else []

    diagram = etree.SubElement(root, q(BPMNDI, 'BPMNDiagram'), id='BPMNDiagram_1')
    plane_ref = collab.get('id') if collab is not None else next(iter(procs))
    plane = etree.SubElement(diagram, q(BPMNDI, 'BPMNPlane'), id='BPMNPlane_1', bpmnElement=plane_ref)

    def shape(el_id, x, y, w, h, **extra):
        s = etree.SubElement(plane, q(BPMNDI, 'BPMNShape'), id=f'{el_id}_di', bpmnElement=el_id, **extra)
        etree.SubElement(s, q(DC, 'Bounds'), x=str(int(x)), y=str(int(y)), width=str(int(w)), height=str(int(h)))

    bounds = {}
    y = 40
    pool_specs = [(p.get('id'), p.get('processRef')) for p in parts] or [(None, pid) for pid in procs]
    # black-box pools span the full diagram width and sit above the white-box
    # pools if their message flows mostly touch the top lane, otherwise below
    white = [s for s in pool_specs if procs.get(s[1]) is not None]
    black = [s for s in pool_specs if procs.get(s[1]) is None]
    if collab is not None and white and black:
        first = procs[white[0][1]]
        leaf = [ln for ln in first.iter(q(BPMN, 'lane')) if ln.find(q(BPMN, 'childLaneSet')) is None]
        lane_ix = {(r.text or '').strip(): i for i, ln in enumerate(leaf) for r in ln.iter(q(BPMN, 'flowNodeRef'))}
        half = (len(leaf) - 1) / 2 if leaf else 0
        mfs = collab.findall(q(BPMN, 'messageFlow'))

        def ends(pid):
            return [f.get('targetRef') if f.get('sourceRef') == pid else f.get('sourceRef')
                    for f in mfs if pid in (f.get('sourceRef'), f.get('targetRef'))]

        def votes(pid):  # endpoints in the upper half of the lanes pull the pool above
            return sum(1 if lane_ix.get(e, 0) <= half else -1 for e in ends(pid))
        above = [s for s in black if votes(s[0]) > 0]
        below = [s for s in black if s not in above]
        # the busiest counterparty sits next to the process
        above.sort(key=lambda s: len(ends(s[0])))
        below.sort(key=lambda s: -len(ends(s[0])))
        pool_specs = above + white + below
    deferred_black = []
    for part_id, pref in pool_specs:
        proc = procs.get(pref)
        if proc is None:  # black-box pool: header bar only, width fixed up below
            shape(part_id, 40, y, 700, 80, isHorizontal='true')
            bounds[part_id] = (40, y, 700, 80)
            deferred_black.append(part_id)
            y += 80 + 40
            continue
        placed, bands, boundary, lanes = layout_process(proc)
        ncols = max((c for c, _, _ in placed.values()), default=0) + 1
        # rows: inherit the row of the first-placed predecessor; a gateway's k-th
        # branch goes k rows down, a boundary event's successor one row down;
        # collisions in a column bump downward
        flows = [(f.get('sourceRef'), f.get('targetRef')) for f in proc.iter(q(BPMN, 'sequenceFlow'))]
        outs_of = defaultdict(list)
        for s_, t_ in flows:
            outs_of[s_].append(t_)
        want = {}
        for nid in sorted(placed, key=lambda n: placed[n][0]):
            if nid in boundary:
                continue
            best = None
            for s_, t_ in flows:
                if t_ != nid:
                    continue
                if s_ in boundary:
                    base = want.get(boundary[s_], 0) + 1
                elif s_ in want:
                    base = want[s_] + (outs_of[s_].index(nid) if placed[s_][2].endswith('Gateway') else 0)
                else:
                    continue
                best = base if best is None else min(best, base)
            want[nid] = best or 0
        rows_in_band = defaultdict(set)
        slot = {}
        for nid in sorted(want, key=lambda n: (placed[n][0], want[n])):
            c, band, _ = placed[nid]
            r = want[nid]
            while r in rows_in_band[(band, c)]:
                r += 1
            slot[nid] = r
            rows_in_band[(band, c)].add(r)
        rows_in_band = {k: max(v) + 1 for k, v in rows_in_band.items()}
        rows_in_band = defaultdict(int, rows_in_band)
        band_rows = {b: max([rows_in_band[(b, c)] for c in range(ncols)] + [1]) for b in bands}
        x0 = 40 + (POOL_HDR if part_id else 0) + (LANE_HDR if bands != [None] else 0)
        width = ncols * COL_W + 2 * PAD_X
        total_h = sum(band_rows[b] * ROW_H + 2 * BAND_PAD for b in bands)
        if part_id:
            shape(part_id, 40, y, width + (x0 - 40), total_h, isHorizontal='true')
            bounds[part_id] = (40, y, width + (x0 - 40), total_h)
        by = y
        band_y = {}
        for b in bands:
            h = band_rows[b] * ROW_H + 2 * BAND_PAD
            band_y[b] = by
            if b:
                lx = 40 + (POOL_HDR if part_id else 0)
                shape(b, lx, by, width + LANE_HDR, h, isHorizontal='true')
            by += h
        # parent lanes span their children
        for lid, d, el in sorted(lanes, key=lambda t: -t[1]):
            if lid in bands:
                continue
            kids = [k for k in bands if k and any(k == r.get('id') for r in el.iter(q(BPMN, 'lane')))]
            if kids:
                top = min(band_y[k] for k in kids)
                bot = max(band_y[k] + band_rows[k] * ROW_H + 2 * BAND_PAD for k in kids)
                lx = 40 + (POOL_HDR if part_id else 0)
                shape(lid, lx, top, width + LANE_HDR, bot - top, isHorizontal='true')
        for nid, (c, band, local) in placed.items():
            if nid in boundary:
                continue
            w, h = SIZE[kind(local)]
            cx = x0 + PAD_X + c * COL_W + COL_W / 2
            cy = band_y[band] + BAND_PAD + slot[nid] * ROW_H + ROW_H / 2
            extra = {'isMarkerVisible': 'true'} if local == 'exclusiveGateway' else {}
            shape(nid, cx - w / 2, cy - h / 2, w, h, **extra)
            bounds[nid] = (cx - w / 2, cy - h / 2, w, h)
        n_on_host = defaultdict(int)
        for b, host in boundary.items():
            hx, hy, hw, hh = bounds[host]
            k = n_on_host[host]
            n_on_host[host] += 1
            bx = hx + 4 + k * 40  # bottom-left: exits stay clear of the main outgoing flow
            shape(b, bx, hy + hh - 18, 36, 36)
            bounds[b] = (bx, hy + hh - 18, 36, 36)
        y = by + 40

    full_w = max([b[2] for k, b in bounds.items() if k not in deferred_black and k in {p.get('id') for p in parts}] + [700])
    for pid in deferred_black:
        x_, y_, _, h_ = bounds[pid]
        bounds[pid] = (x_, y_, full_w, h_)
        for s in plane.findall(q(BPMNDI, 'BPMNShape')):
            if s.get('bpmnElement') == pid:
                s.find(q(DC, 'Bounds')).set('width', str(int(full_w)))

    def center(i):
        x, yy, w, h = bounds[i]
        return x + w / 2, yy + h / 2

    boundary = {n.get('id'): n.get('attachedToRef') for p_ in procs.values()
                for n in p_.iter(q(BPMN, 'boundaryEvent'))}
    nodes_by_id = {n.get('id'): n for p_ in procs.values() for n in p_.iter()
                   if isinstance(n.tag, str) and n.get('id')}
    pool_ids = {p.get('id') for p in parts}

    def shape_kind(i):
        if i in pool_ids or bounds[i][2] >= 300:
            return 'pool'
        el = nodes_by_id.get(i)
        return kind(etree.QName(el).localname) if el is not None else 'task'

    # ---- 1. candidate routes --------------------------------------------
    def default_route(s, t):
        (sx, sy), (tx, ty) = center(s), center(t)
        x1, y1, w1, h1 = bounds[s]
        x2, y2, w2, h2 = bounds[t]
        if shape_kind(s) == 'gateway' and abs(sy - ty) >= 1 and tx > sx + 1:
            # gateway branch to another row: leave from the top/bottom vertex so
            # each branch has its own horizontal run (and label) into its target
            return [(sx, y1 + h1 if ty > sy else y1), (sx, ty), (x2, ty)]
        if abs(sy - ty) < 1:
            return [(x1 + w1, sy), (x2, ty)] if tx >= sx else [(x1, sy), (x2 + w2, ty)]
        if shape_kind(t) == 'gateway' and tx > sx + 1 and shape_kind(s) != 'event' \
                and indeg.get(t, 0) > 1:
            # merge from another row: enter at the top/bottom vertex so arrowheads
            # from different rows never stack on the left vertex
            return [(x1 + w1, sy), (tx, sy), (tx, y2 if sy < ty else y2 + h2)]
        if tx > sx + 1 and shape_kind(s) == 'event' and ty > sy:
            # event (e.g. boundary) dropping to a lower row: leave from the bottom
            return [(sx, y1 + h1), (sx, ty), (x2, ty)]
        if tx > sx + 1:
            mid = x1 + w1 + 20
            return [(x1 + w1, sy), (mid, sy), (mid, ty), (x2, ty)]
        # backward or same column: route below/above
        return [(sx, y1 + h1 if ty > sy else y1), (sx, ty), (x2 + w2 if tx < sx else x2, ty)]

    def obstacles(s, t):
        host = boundary.get(s)
        return [b for k, b in bounds.items()
                if b[2] < 300 and k not in (s, t, host) and boundary.get(k) not in (s, t)]

    def segs(pts):
        return list(zip(pts, pts[1:]))

    def hits(pts, obs, pad=-2):
        n = 0
        for (ax, ay), (bx, by) in segs(pts):
            lx, hx = sorted((ax, bx)); ly, hy = sorted((ay, by))
            n += sum(lx < ox + ow + pad and hx > ox - pad and ly < oy + oh + pad and hy > oy - pad
                     for ox, oy, ow, oh in obs)
        return n

    def plen(pts):
        return sum(abs(bx - ax) + abs(by - ay) for (ax, ay), (bx, by) in segs(pts))

    def alternatives(s, t, obs):
        """Z-routes through column gutters and U-routes through row channels."""
        x1, y1, w1, h1 = bounds[s]
        x2, y2, w2, h2 = bounds[t]
        sx, sy, tx, ty = x1 + w1 / 2, y1 + h1 / 2, x2 + w2 / 2, y2 + h2 / 2
        cands = []
        xs = sorted({v for ox, oy, ow, oh in obs for v in (ox - 14, ox + ow + 14)} |
                    {x1 + w1 + 20, x2 - 20})
        ys = sorted({v for ox, oy, ow, oh in obs for v in (oy - 14, oy + oh + 14)} |
                    {y1 - 20, y1 + h1 + 20, y2 - 20, y2 + h2 + 20})
        if tx > sx:  # forward: right side out, left side in, vertical in a gutter
            for mx in xs:
                if x1 + w1 < mx < x2:
                    cands.append([(x1 + w1, sy), (mx, sy), (mx, ty), (x2, ty)])
        for cy in ys:  # channel: out top/bottom, across, in top/bottom
            a = (sx, y1 if cy < sy else y1 + h1)
            b = (tx, y2 if cy < ty else y2 + h2)
            cands.append([a, (sx, cy), (tx, cy), b])
        return cands

    def crossings(pts, used):
        n = 0
        for (ax, ay), (bx, by) in segs(pts):
            for (cx, cy), (dx, dy) in used:
                if abs(ax - bx) < .5 and abs(cy - dy) < .5:      # mine vertical, theirs horizontal
                    n += min(cx, dx) + 1 < ax < max(cx, dx) - 1 and min(ay, by) + 1 < cy < max(ay, by) - 1
                elif abs(ay - by) < .5 and abs(cx - dx) < .5:    # mine horizontal, theirs vertical
                    n += min(ax, bx) + 1 < cx < max(ax, bx) - 1 and min(cy, dy) + 1 < ay < max(cy, dy) - 1
        return n

    def shared(pts, used):
        tot = 0
        for (ax, ay), (bx, by) in segs(pts):
            for (cx, cy), (dx, dy) in used:
                if abs(ax - bx) < .5 and abs(cx - dx) < .5 and abs(ax - cx) < .5:
                    tot += max(0, min(max(ay, by), max(cy, dy)) - max(min(ay, by), min(cy, dy)))
                elif abs(ay - by) < .5 and abs(cy - dy) < .5 and abs(ay - cy) < .5:
                    tot += max(0, min(max(ax, bx), max(cx, dx)) - max(min(ax, bx), min(cx, dx)))
        return tot

    indeg = defaultdict(int)
    for p_ in procs.values():
        for f in p_.iter(q(BPMN, 'sequenceFlow')):
            indeg[f.get('targetRef')] += 1
    BEND, CROSS, SHARE = 30, 220, 0.6
    routes = {}  # fid -> [s, t, [[x, y], ...]]   (insertion order = output order)

    def route_flow(fid, s, t):
        """Sequential routing: cheapest shape-free candidate given the edges
        already routed (length + bends + crossings + shared track)."""
        d = default_route(s, t)
        obs = obstacles(s, t)
        cands = [d] + alternatives(s, t, obs)
        if s in boundary:
            by = bounds[s][1] + bounds[s][3]
            cands = [c for c in cands if abs(c[0][1] - by) < 1 and c[1][1] > c[0][1]] or cands
        clear = [c for c in cands if not hits(c, obs, 10)] or \
                [c for c in cands if not hits(c, obs)] or [d]
        used = [sg for _, _, p in routes.values() for sg in segs([tuple(v) for v in p])]
        best = min(clear, key=lambda c: plen(c) + BEND * (len(c) - 2)
                   + CROSS * crossings(c, used) + SHARE * shared(c, used))
        routes[fid] = [s, t, [list(v) for v in best]]

    def route_message(fid, s, t):
        (sx, sy), (tx, ty) = center(s), center(t)
        sxx, syy, sw, sh = bounds[s]
        txx, tyy, tw, th = bounds[t]
        x = sx if sw < 300 else tx  # vertical connector at the flow-node end
        y1 = syy + sh if ty > sy else syy
        y2 = tyy if ty > sy else tyy + th
        lo, hi = sorted((y1, y2))
        node_end = s if sw < 300 else t
        nx, ny, nw, nh = bounds[node_end]
        blocked = any(k not in (s, t) and k not in pool_ids and b[2] < 300 and
                      b[0] - 4 <= x <= b[0] + b[2] + 4 and lo < b[1] + b[3] and b[1] < hi
                      for k, b in bounds.items())
        if blocked:  # leave the node from its side and climb in the column gutter
            gx = nx + nw / 2 + COL_W / 2 - 6
            ncy = ny + nh / 2
            far = y2 if node_end == s else y1
            side = [(nx + nw, ncy), (gx, ncy), (gx, far)]
            pts = side if node_end == s else side[::-1]
        else:
            pts = [(x, y1), (x, y2)]
        routes[fid] = [s, t, [list(v) for v in pts]]

    for proc in procs.values():
        for f in proc.iter(q(BPMN, 'sequenceFlow')):
            if f.get('sourceRef') in bounds and f.get('targetRef') in bounds:
                route_flow(f.get('id'), f.get('sourceRef'), f.get('targetRef'))
    if collab is not None:
        for f in collab.findall(q(BPMN, 'messageFlow')):
            if f.get('sourceRef') in bounds and f.get('targetRef') in bounds:
                route_message(f.get('id'), f.get('sourceRef'), f.get('targetRef'))

    # ---- 2. nudging (track assignment) ----------------------------------
    # Parallel segments of different edges that share a line are spread
    # across the channel, ordered so that where each one turns next does not
    # cross its neighbours (Wybrow, Marriott & Stuckey 2009, simplified).
    # Endpoints that sit on a node slide along its outline (port spreading).
    TRACK = 8

    def snap(node, pt, axis):
        x, y, w, h = bounds[node]
        k = shape_kind(node)
        if k == 'pool':
            return
        cx, cy = x + w / 2, y + h / 2
        if axis == 'v':   # x moved; pt is on the top or bottom of the node
            d = pt[0] - cx
            ext = h / 2 - abs(d) * h / w if k == 'gateway' else \
                (max(0.0, (w / 2) ** 2 - d * d) ** .5 if k == 'event' else h / 2)
            pt[1] = cy - ext if pt[1] < cy else cy + ext
        else:             # y moved; pt is on the left or right side
            d = pt[1] - cy
            ext = w / 2 - abs(d) * w / h if k == 'gateway' else \
                (max(0.0, (h / 2) ** 2 - d * d) ** .5 if k == 'event' else w / 2)
            pt[0] = cx - ext if pt[0] < cx else cx + ext

    def port_room(fid, i, axis):
        """How far a segment may move along a node outline (None = free)."""
        s, t, p = routes[fid]
        room = None
        for idx, node in ((0, s), (len(p) - 1, t)):
            if idx in (i, i + 1) and shape_kind(node) == 'gateway' and idx == len(p) - 1:
                return (0.0, 0.0)   # arrowheads stay on the gateway vertex; fan-outs may spread
            if idx in (i, i + 1) and shape_kind(node) != 'pool':
                x, y, w, h = bounds[node]
                half, c = (w / 2, x + w / 2) if axis == 'v' else (h / 2, y + h / 2)
                coord = p[idx][0] if axis == 'v' else p[idx][1]
                r = (c - coord, c + half * 0.6 - coord, c - half * 0.6 - coord)
                lim = (r[2], r[1])
                room = lim if room is None else (max(room[0], lim[0]), min(room[1], lim[1]))
        return room

    def order_key(fid, i, axis, hi_end):
        p = routes[fid][2]
        a = 1 if axis == 'v' else 0        # coordinate along the segment
        o = 1 - a                          # coordinate across it
        far = i if p[i][a] > p[i + 1][a] else i + 1   # bottom / right end
        nb = far + 1 if far == i + 1 else far - 1
        d = 0
        if 0 <= nb < len(p):
            diff = p[nb][o] - p[far][o]
            d = (diff > .5) - (diff < -.5)
        return (d, -d * hi_end)

    for _ in range(3):
        sl = []
        for fid, (_, _, p) in routes.items():
            for i in range(len(p) - 1):
                (ax, ay), (bx, by) = p[i], p[i + 1]
                if abs(ax - bx) < .5 and abs(ay - by) > .5:
                    sl.append((fid, i, 'v', ax, min(ay, by), max(ay, by)))
                elif abs(ay - by) < .5 and abs(ax - bx) > .5:
                    sl.append((fid, i, 'h', ay, min(ax, bx), max(ax, bx)))
        parent = list(range(len(sl)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a
        line = defaultdict(list)
        for k, sg in enumerate(sl):
            line[(sg[2], round(sg[3]))].append(k)
        for ks in line.values():
            for ia in range(len(ks)):
                for ib in range(ia + 1, len(ks)):
                    A, B = sl[ks[ia]], sl[ks[ib]]
                    if A[0] != B[0] and min(A[5], B[5]) - max(A[4], B[4]) > 2:
                        parent[find(ks[ia])] = find(ks[ib])
        groups = defaultdict(list)
        for k in range(len(sl)):
            groups[find(k)].append(k)
        moved = False
        for ks in groups.values():
            if len({sl[k][0] for k in ks}) < 2:
                continue
            ks.sort(key=lambda k: order_key(sl[k][0], sl[k][1], sl[k][2], sl[k][5]))
            n = len(ks)
            for step in (TRACK, 6, 4, 3):
                offs = [(j - (n - 1) / 2) * step for j in range(n)]
                ok = True
                for k, off in zip(ks, offs):
                    room = port_room(sl[k][0], sl[k][1], sl[k][2])
                    if room and not (room[0] - .01 <= off <= room[1] + .01):
                        ok = False
                if ok:
                    break
            else:
                continue
            for k, off in zip(ks, offs):
                if abs(off) < .01:
                    continue
                fid, i, axis, coord = sl[k][:4]
                s, t, p = routes[fid]
                a = 0 if axis == 'v' else 1
                for idx in (i, i + 1):
                    p[idx][a] = coord + off
                if i == 0:
                    snap(s, p[0], axis)
                if i + 1 == len(p) - 1:
                    snap(t, p[-1], axis)
                moved = True
        if not moved:
            break

    for fid, (_, _, p) in routes.items():
        e = etree.SubElement(plane, q(BPMNDI, 'BPMNEdge'), id=f'{fid}_di', bpmnElement=fid)
        for px, py in p:
            etree.SubElement(e, q(DI, 'waypoint'), x=str(int(round(px))), y=str(int(round(py))))
    return root


def main(argv=None):
    ap = argparse.ArgumentParser(description='Add BPMNDI layout')
    ap.add_argument('file')
    ap.add_argument('--in-place', action='store_true')
    a = ap.parse_args(argv)
    with open(a.file, 'rb') as fh:
        raw = fh.read()
    parser = etree.XMLParser(remove_blank_text=False)
    root = etree.fromstring(raw, parser)
    nsmap = dict(root.nsmap)
    if not all(u in nsmap.values() for u in (BPMNDI, DC, DI)):
        # rebuild root with DI prefixes declared (lxml can't add nsmap in place)
        nsmap.update({k: v for k, v in (('bpmndi', BPMNDI), ('dc', DC), ('di', DI)) if v not in nsmap.values()})
        new = etree.Element(root.tag, nsmap=nsmap, attrib=dict(root.attrib))
        new.text = root.text
        for c in list(root):
            new.append(c)
        prev = root.getprevious()
        comments = []
        while prev is not None:
            comments.insert(0, prev)
            prev = prev.getprevious()
        root = new
        for cm in comments:
            root.addprevious(cm)
    build(root)
    for el in root.iter(q(BPMNDI, 'BPMNDiagram')):
        etree.indent(el, space='  ', level=1)
        el.tail = '\n'
        prev = el.getprevious()
        if prev is not None:
            prev.tail = '\n\n  '
    out = etree.tostring(root.getroottree(), xml_declaration=True, encoding='UTF-8').decode('utf-8')
    out = out.replace("<?xml version='1.0' encoding='UTF-8'?>", '<?xml version="1.0" encoding="UTF-8"?>')
    if not out.endswith('\n'):
        out += '\n'
    if a.in_place:
        with open(a.file, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(out)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
