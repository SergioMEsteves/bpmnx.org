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
    edges = [(u, v, 1) for u in succ for v in succ[u]] + [(h, b, 0) for b, h in boundary.items() if h in nodes]
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
    for part_id, pref in pool_specs:
        proc = procs.get(pref)
        if proc is None:  # black-box pool: header bar only
            shape(part_id, 40, y, 700, 80, isHorizontal='true')
            bounds[part_id] = (40, y, 700, 80)
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
            bx = hx + hw - 36 - 4 - k * 40
            shape(b, bx, hy + hh - 18, 36, 36)
            bounds[b] = (bx, hy + hh - 18, 36, 36)
        y = by + 40

    def center(i):
        x, yy, w, h = bounds[i]
        return x + w / 2, yy + h / 2

    def edge(fid, s, t):
        if s not in bounds or t not in bounds:
            return
        e = etree.SubElement(plane, q(BPMNDI, 'BPMNEdge'), id=f'{fid}_di', bpmnElement=fid)
        (sx, sy), (tx, ty) = center(s), center(t)
        x1, y1, w1, h1 = bounds[s]
        x2, y2, w2, h2 = bounds[t]
        pts = []
        if abs(sy - ty) < 1:
            pts = [(x1 + w1, sy), (x2, ty)] if tx >= sx else [(x1, sy), (x2 + w2, ty)]
        elif tx > sx + 1 and w1 == 36 and h1 == 36 and ty > sy:
            # event (e.g. boundary) dropping to a lower row: leave from the bottom
            pts = [(sx, y1 + h1), (sx, ty), (x2, ty)]
        elif tx > sx + 1:
            mid = x1 + w1 + 20
            pts = [(x1 + w1, sy), (mid, sy), (mid, ty), (x2, ty)]
        else:  # backward or same column: route below/above
            pts = [(sx, y1 + h1 if ty > sy else y1), (sx, ty), (x2 + w2 if tx < sx else x2, ty)]
        for px, py in pts:
            etree.SubElement(e, q(DI, 'waypoint'), x=str(int(px)), y=str(int(py)))

    for proc in procs.values():
        for f in proc.iter(q(BPMN, 'sequenceFlow')):
            edge(f.get('id'), f.get('sourceRef'), f.get('targetRef'))
    if collab is not None:
        for f in collab.findall(q(BPMN, 'messageFlow')):
            s, t = f.get('sourceRef'), f.get('targetRef')
            if s not in bounds or t not in bounds:
                continue
            e = etree.SubElement(plane, q(BPMNDI, 'BPMNEdge'), id=f"{f.get('id')}_di", bpmnElement=f.get('id'))
            (sx, sy), (tx, ty) = center(s), center(t)
            sxx, syy, sw, sh = bounds[s]
            txx, tyy, tw, th = bounds[t]
            # vertical connector at the x of whichever end is a flow node
            x = sx if sw < 300 else tx
            y1 = syy + sh if ty > sy else syy
            y2 = tyy if ty > sy else tyy + th
            for py in (y1, y2):
                etree.SubElement(e, q(DI, 'waypoint'), x=str(int(x)), y=str(int(py)))
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
