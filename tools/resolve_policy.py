#!/usr/bin/env python3
"""BPMNx effective-policy resolver (CLI).

For every enhanced element, folds the scope chain
    [participant (whiteBox)] -> [lane (outer) -> ... -> lane (inner)] -> [element]
per spec §6 and prints the effective guardrails with the scope each value came
from. Implemented in bpmnx_core.py (a port of the BPMNx Bench engine).

Usage:
  python tools/resolve_policy.py FILE.bpmn [--json]
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpmnx_core as core  # noqa: E402


def resolve(path):
    m = core.parse_model(path)
    if not m.ok:
        raise SystemExit(f'cannot parse {path}: {m.parseError}')
    out = []
    for n in m.nodes.values():
        if not n['enh']:
            continue
        p = core.effective_policy(m, n)
        out.append(dict(
            id=n['id'], name=n['name'], determinism=n['enh']['determinism'],
            chain=[f"{c['scope']}:{c['owner']}" for c in p['chain']],
            toolAllow=[(t['ref'], t['frm']) for t in p['toolAllow']],
            toolDeny=[(t['ref'], t['frm']) for t in p['toolDeny']],
            overridden=p['overridden'],
            constraints=[(c.get('type') or '', c['text'], c['frm']) for c in p['constraints']],
            confidenceThreshold=(p['confidenceThreshold']['val'], p['confidenceThreshold']['frm']),
            maxSteps=(p['maxSteps']['val'], p['maxSteps']['frm']),
            timeBudget=(p['timeBudget']['val'], p['timeBudget']['frm']),
            retryPolicy=(p['retryPolicy']['val'], p['retryPolicy']['frm']),
            audited=(p['audited']['val'], p['audited']['frm']),
            irreversible=p['irreversible']['val']))
    return m, out


def _fmt(xs):
    return ', '.join(f'{v} <{s}>' for v, s in xs) or '-'


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='BPMNx effective-policy resolver')
    ap.add_argument('file')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    m, res = resolve(a.file)
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    print(f'BPMNx {m.bpmnxVersion} effective-policy resolution: {a.file}')
    print('=' * 72)
    for r in res:
        kind = 'AI' if r['determinism'] == 'nondeterministic' else 'Program'
        print(f"\n* {r['name'] or r['id']}  (id={r['id']}, {kind})")
        print(f"   scope chain   : {' -> '.join(r['chain']) or '-'}")
        print(f"   tools allowed : {_fmt(r['toolAllow'])}")
        print(f"   tools denied  : {_fmt(r['toolDeny'])}")
        for o in r['overridden']:
            print(f"   OVERRIDDEN    : {o['ref']} (allowed at {o['allowedBy']}, denied at {o['deniedBy']})")
        for key, label in (('confidenceThreshold', 'confidence   '), ('maxSteps', 'max steps    '),
                           ('timeBudget', 'time budget  '), ('retryPolicy', 'retry policy ')):
            v, s = r[key]
            if v is not None:
                print(f'   {label} : {v} <{s}>')
        v, s = r['audited']
        print(f"   audited       : {f'true <{s}>' if v else 'false'}")
        if r['irreversible']:
            print('   irreversible  : true (human approval required before side effect)')
        if r['constraints']:
            print('   constraints   :')
            for t, txt, s in r['constraints']:
                print(f'      [{t}] {txt} <{s}>')
    print('\nProvenance in <angle brackets> is the scope that set the effective value.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
