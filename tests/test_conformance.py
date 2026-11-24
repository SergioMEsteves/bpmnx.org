"""Expected diagnostics for every example and fixture.

Each fixture declares its expectation in an XML comment:
    <!-- expect: E-CODE@ref W-CODE@ref ... -->   (or "expect: none")
The examples are listed in EXAMPLES below.
"""
import glob
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import bpmnx_core as core  # noqa: E402
import migrate_1_0_to_1_1 as mig  # noqa: E402

EXAMPLES = {
    'examples/01-element-enhancement.bpmn': set(),
    'examples/02-lane-inheritance.bpmn': {'E-CONTRADICTION@Task_Classify'},
    'examples/02b-lane-inheritance-clean.bpmn': set(),
    'examples/03-participant-blackbox.bpmn': set(),
}


def got(path):
    _, diags = core.check_file(path)
    return {f"{d['code']}@{d['ref']}" if d['ref'] else d['code']
            for d in diags if d['severity'] in ('error', 'warning')}


@pytest.mark.parametrize('rel,want', sorted(EXAMPLES.items()))
def test_examples(rel, want):
    assert got(os.path.join(ROOT, rel)) == want


FIXTURES = sorted(glob.glob(os.path.join(ROOT, 'tests', 'fixtures', '**', '*.bpmn'), recursive=True))


@pytest.mark.parametrize('path', FIXTURES, ids=lambda p: os.path.relpath(p, ROOT))
def test_fixture(path):
    src = open(path, encoding='utf-8').read()
    m = re.search(r'<!--\s*expect:\s*(.*?)\s*-->', src, re.S)
    if not m:
        pytest.skip('no expect comment')
    want = set() if m.group(1).strip() == 'none' else set(m.group(1).split())
    # schema errors are noisy duplicates of engine errors; fixtures list engine codes only
    assert {g for g in got(path) if not g.startswith('E-SCHEMA')} == want


def test_policy_02b():
    m = core.parse_model(os.path.join(ROOT, 'examples/02b-lane-inheritance-clean.bpmn'))
    p = core.effective_policy(m, m.nodes['Task_Classify'])
    assert sorted(t['ref'] for t in p['toolDeny']) == ['billing', 'email.send']
    assert p['confidenceThreshold']['val'] == 0.8
    assert p['audited']['val'] is True


@pytest.mark.parametrize('rel', sorted(EXAMPLES))
def test_migration_roundtrip(rel):
    """1.1 examples rendered back to 1.0 and migrated forward are identical."""
    src = open(os.path.join(ROOT, rel), encoding='utf-8').read()
    as10 = src.replace(mig.NS11, mig.NS10).replace('version="1.1"', 'version="1.0"')
    assert mig.migrate(as10) == src
