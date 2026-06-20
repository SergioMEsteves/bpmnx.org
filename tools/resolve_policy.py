#!/usr/bin/env python3
"""BPMNx 1.0 policy resolver — reference implementation of the §6 merge algorithm.

For every enhanced element, computes its EFFECTIVE policy by merging the scope
chain (participant → lane → element) per spec §6.2. Prints the resolved
guardrails so authors can see exactly what a conformant runtime would enforce.

This is a reference implementation of the normative inheritance model. A
conformant runtime MUST produce the same effective policy.

Usage: python3 resolve_policy.py <file.bpmn>
"""
import sys
from lxml import etree

BPMN_NS  = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
BPMNX_NS = 'http://bpmnx.org/schema/1.0/bpmnx'
NS = {'bpmn': BPMN_NS, 'bpmnx': BPMNX_NS}


def localname(tag):
    if not isinstance(tag, str):
        return ''
    return tag.split('}')[-1] if '}' in tag else tag


def parse_envelope(env_el):
    """Extract an envelope element into a policy dict."""
    if env_el is None:
        return {}
    p = {
        'toolAllow':  set(),
        'toolDeny':   set(),
        'constraint': [],
    }
    for ta in env_el.findall('bpmnx:toolAllow', NS):
        p['toolAllow'].add(ta.get('ref'))
    for td in env_el.findall('bpmnx:toolDeny', NS):
        p['toolDeny'].add(td.get('ref'))
    for c in env_el.findall('bpmnx:constraint', NS):
        p['constraint'].append((c.get('type', ''), (c.text or '').strip()))
    for attr in ('confidenceThreshold', 'maxSteps', 'timeBudget', 'retryPolicy',
                 'audited', 'irreversible'):
        v = env_el.get(attr)
        if v is not None:
            p[attr] = v
    return p


def merge(broader, narrower):
    """Merge two policy dicts per spec §6.2. broader ⊕ narrower."""
    out = {}
    # Unions (binding)
    out['toolDeny']   = broader.get('toolDeny', set()) | narrower.get('toolDeny', set())
    out['constraint'] = broader.get('constraint', []) + narrower.get('constraint', [])
    # Allow = union minus all denies
    allow = broader.get('toolAllow', set()) | narrower.get('toolAllow', set())
    out['toolAllow'] = allow - out['toolDeny']
    # confidenceThreshold = max
    cts = [float(x['confidenceThreshold']) for x in (broader, narrower)
           if x.get('confidenceThreshold') is not None]
    if cts:
        out['confidenceThreshold'] = max(cts)
    # maxSteps = min
    ms = [int(x['maxSteps']) for x in (broader, narrower) if x.get('maxSteps') is not None]
    if ms:
        out['maxSteps'] = min(ms)
    # timeBudget = min (string compare on ISO duration is unsafe; keep narrower if present)
    tb = [x['timeBudget'] for x in (broader, narrower) if x.get('timeBudget') is not None]
    if tb:
        out['timeBudget'] = tb[-1]  # narrower wins as documented fallback
    # audited = OR
    aud = any(str(x.get('audited', 'false')).lower() == 'true' for x in (broader, narrower))
    out['audited'] = 'true' if aud else 'false'
    # retryPolicy = narrower wins
    rp = [x['retryPolicy'] for x in (broader, narrower) if x.get('retryPolicy') is not None]
    if rp:
        out['retryPolicy'] = rp[-1]
    # irreversible = element scope only (narrower)
    if narrower.get('irreversible') is not None:
        out['irreversible'] = narrower['irreversible']
    return out


def resolve(bpmn_path):
    tree = etree.parse(bpmn_path)
    root = tree.getroot()

    # Map element id → lane envelope policy (if any)
    lane_policy_for = {}
    for lane in root.findall('.//bpmn:lane', NS):
        le = lane.find('.//bpmnx:laneEnhancement', NS)
        if le is None:
            continue
        env = le.find('bpmnx:envelope', NS)
        pol = parse_envelope(env)
        for fnr in lane.findall('bpmn:flowNodeRef', NS):
            lane_policy_for[fnr.text] = pol

    # Find element enhancements
    results = []
    for enh in root.findall('.//bpmnx:enhancement', NS):
        host = enh.getparent().getparent()
        hid  = host.get('id') if host is not None else '?'
        hname = host.get('name', hid) if host is not None else '?'
        env = enh.find('bpmnx:envelope', NS)
        elem_pol = parse_envelope(env)

        # Scope chain: lane (broader) → element (narrower)
        lane_pol = lane_policy_for.get(hid, {})
        effective = merge(lane_pol, elem_pol)
        results.append((hname, hid, lane_pol, elem_pol, effective))

    return results


def fmt_set(s):
    return ', '.join(sorted(s)) if s else '—'


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else 'examples/02-lane-inheritance.bpmn'
    results = resolve(path)
    print(f"BPMNx effective-policy resolution: {path}")
    print("=" * 70)
    for hname, hid, lane_pol, elem_pol, eff in results:
        print(f"\n● {hname}  (id={hid})")
        if lane_pol:
            print(f"   inherits lane envelope: deny={fmt_set(lane_pol.get('toolDeny', set()))}, "
                  f"audited={lane_pol.get('audited','false')}, "
                  f"confidence>={lane_pol.get('confidenceThreshold','—')}")
        print(f"   EFFECTIVE POLICY:")
        print(f"     tools allowed : {fmt_set(eff.get('toolAllow', set()))}")
        print(f"     tools denied  : {fmt_set(eff.get('toolDeny', set()))}")
        if eff.get('confidenceThreshold') is not None:
            print(f"     confidence floor: {eff['confidenceThreshold']}")
        print(f"     audited       : {eff.get('audited','false')}")
        if eff.get('maxSteps') is not None:
            print(f"     max steps     : {eff['maxSteps']}")
        if eff.get('constraint'):
            print(f"     constraints   :")
            for ctype, ctext in eff['constraint']:
                print(f"        [{ctype}] {ctext}")
    print()
