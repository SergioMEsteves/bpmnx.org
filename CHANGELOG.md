# Changelog

## 1.1 — 2026-11

Spec: see `spec/SPECIFICATION.md` §10 for the normative changes.

- **Namespace** `http://bpmnx.org/schema/1.1/bpmnx`, `version="1.1"`. 1.0
  documents are still accepted (`W-LEGACY-NS`); mixing is `E-NS-MIXED`.
- **Determinism** is now defined as AI (nondeterministic, model judgment) vs
  Program (deterministic logic an agent drives as a tool).
- **Typed boundary events** are enhanceable; `intermediateThrowEvent` is not.
- **Drawn routes:** `onFailRef`/`targetRef` must be reachable by sequence flow
  (`E-REF-UNREACHABLE`). AI gateway outcomes need named flows (`W-GW-OUTCOME`,
  `W-GW-FLOW`).
- **Nested lanes** (`childLaneSet`) inherit outer → inner.
- **Irreversible gate** is a human element immediately upstream.
- **Bench** moved to `bench/index.html` and is the reference implementation.
- **Tools** rebuilt on `tools/bpmnx_core.py`, a port of the Bench engine:
  - participant scope now resolved;
  - `timeBudget` merges by minimum;
  - pool contradictions and irreversible gating are checked.
  New: `migrate_1_0_to_1_1.py`, `add_bpmndi.py`.
- **Examples** migrated to 1.1 with BPMNDI. Example 01 now draws its escalation
  and review-failure routes, routes the `disqualified` outcome, and shows an
  irreversible Program step behind a human gate.
- **Repo:** README no longer duplicates the spec. Added `requirements.txt`,
  tests, parity check and CI.

## 1.0

Initial draft.
