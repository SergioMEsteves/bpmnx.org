"""Emit the Python engine's normalized output for tests/parity.mjs (JSON on stdout)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import bpmnx_core as core  # noqa: E402


def dump(path):
    m = core.parse_model(path)
    if not m.ok:
        return {'ok': False}
    diags = sorted([d['severity'], d['code'], d['ref']] for d in core.validate(m) if d['severity'] != 'ok')
    policies = {}
    for n in m.nodes.values():
        if not n['enh']:
            continue
        p = core.effective_policy(m, n)
        policies[n['id']] = {
            'chain': [c['scope'] for c in p['chain']],
            'toolAllow': sorted(t['ref'] for t in p['toolAllow']),
            'toolDeny': sorted(t['ref'] for t in p['toolDeny']),
            'overridden': sorted(o['ref'] for o in p['overridden']),
            'constraints': [c['text'] for c in p['constraints']],
            'confidenceThreshold': p['confidenceThreshold']['val'],
            'maxSteps': p['maxSteps']['val'],
            'timeBudget': p['timeBudget']['val'],
            'retryPolicy': p['retryPolicy']['val'],
            'audited': p['audited']['val'],
            'irreversible': p['irreversible']['val'],
        }
    return {'ok': True, 'version': m.bpmnxVersion, 'diags': diags, 'policies': policies}


def norm(o):
    # match JS JSON: integral floats print without ".0"
    if isinstance(o, float) and o.is_integer():
        return int(o)
    if isinstance(o, dict):
        return {k: norm(v) for k, v in o.items()}
    if isinstance(o, list):
        return [norm(v) for v in o]
    return o


if __name__ == '__main__':
    print(json.dumps({p: norm(dump(p)) for p in sys.argv[1:]}, ensure_ascii=False))
