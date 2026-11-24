#!/usr/bin/env python3
"""Migrate a BPMNx 1.0 document to BPMNx 1.1 (spec §9).

Rewrites the namespace URI and every version="1.0" attribute on BPMNx scope
markers. Everything else is untouched, text-level, so comments, formatting
and attribute order survive. 1.1 adds no required attributes, so a conformant
1.0 document migrates to a conformant 1.1 document. Run the validator after
migrating: 1.1 adds checks (§4.3 reachability, §4.4 gateway outcomes) that
may flag problems 1.0 tooling missed.

Usage:
  python tools/migrate_1_0_to_1_1.py FILE.bpmn [FILE.bpmn ...] [--in-place]
"""
import argparse
import re
import sys

NS10 = 'http://bpmnx.org/schema/1.0/bpmnx'
NS11 = 'http://bpmnx.org/schema/1.1/bpmnx'
_MARKER = re.compile(
    r'(<(?P<p>[A-Za-z_][\w.-]*):(?:enhancement|laneEnhancement|participantEnhancement)\b[^>]*?\bversion\s*=\s*)(["\'])1\.0\3')


def migrate(text):
    prefixes = set(re.findall(r'xmlns:([A-Za-z_][\w.-]*)\s*=\s*["\']' + re.escape(NS10), text))
    text = text.replace(NS10, NS11)

    def bump(m):
        return m.group(1) + m.group(3) + '1.1' + m.group(3) if m.group('p') in prefixes else m.group(0)

    return _MARKER.sub(bump, text)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Migrate BPMNx 1.0 -> 1.1')
    ap.add_argument('files', nargs='+')
    ap.add_argument('--in-place', action='store_true')
    a = ap.parse_args(argv)
    for f in a.files:
        with open(f, encoding='utf-8', newline='') as fh:
            src = fh.read()
        out = migrate(src)
        if a.in_place:
            with open(f, 'w', encoding='utf-8', newline='') as fh:
                fh.write(out)
            print(f'migrated {f}', file=sys.stderr)
        else:
            sys.stdout.write(out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
