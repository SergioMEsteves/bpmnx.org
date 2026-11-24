#!/usr/bin/env python3
"""BPMNx conformance validator (CLI).

Runs the BPMNx 1.1 conformance rules (spec §7.1) over one or more .bpmn files.
The rules are implemented in bpmnx_core.py, a port of the BPMNx Bench engine
(bench/index.html), which is authoritative. In addition to the Bench checks,
every BPMNx marker is validated against the XSD for its namespace.

Documents in the 1.0 namespace are accepted as legacy: they are checked under
1.1 rules, against the 1.0 XSD, with a W-LEGACY-NS warning.

Usage:
  python tools/validate_bpmnx.py FILE.bpmn [FILE.bpmn ...] [--json] [--strict]

  --json    machine-readable output
  --strict  treat warnings as errors

Exit code: 0 = conformant, 1 = errors (or warnings with --strict), 2 = usage.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpmnx_core as core  # noqa: E402

GLYPH = {'error': '\u2717', 'warning': '!', 'ok': '\u2713'}


def summarize(m):
    enh = [n for n in m.nodes.values() if n['enh']]
    ai = sum(1 for n in enh if n['enh']['determinism'] == 'nondeterministic')
    lanes = sum(1 for l in m.lanes.values() if l['enh'])
    parts = sum(1 for p in m.participants.values() if p['enh'])
    return (f"BPMNx {m.bpmnxVersion}{' (legacy namespace)' if m.legacy else ''} · "
            f"{len(enh)} element ({ai} AI, {len(enh) - ai} Program) · {lanes} lane · {parts} participant")


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='BPMNx conformance validator')
    ap.add_argument('files', nargs='+')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--strict', action='store_true')
    a = ap.parse_args(argv)

    report, failed = {}, False
    for path in a.files:
        m, diags = core.check_file(path)
        errs = [d for d in diags if d['severity'] == 'error']
        warns = [d for d in diags if d['severity'] == 'warning']
        bad = bool(errs) or (a.strict and bool(warns))
        failed |= bad
        report[path] = dict(conformant=not bad, version=m.bpmnxVersion if m.ok else None,
                            diagnostics=[d for d in diags if d['severity'] != 'ok'])
        if a.json:
            continue
        print(path)
        if m.ok:
            print(f'  {summarize(m)}')
        for d in diags:
            if d['severity'] == 'ok':
                continue
            ref = f" [{d['ref']}]" if d['ref'] else ''
            print(f"  {GLYPH[d['severity']]} {d['code']}{ref}: {d['message']}")
        verdict = 'NOT CONFORMANT' if bad else 'CONFORMANT'
        print(f'  => {verdict} ({len(errs)} error(s), {len(warns)} warning(s))\n')

    if a.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
