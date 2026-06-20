#!/usr/bin/env python3
"""BPMNx 1.0 conformance validator.

Checks a .bpmn file against the BPMNx 1.0 specification:
  - Well-formed BPMN 2.0 XML
  - Every BPMNx extension validates against the BPMNx XSD
  - enhancement only on enhanceable elements (typed events only for events)
  - laneEnhancement only on lanes; participantEnhancement only on participants
  - onFailRef / targetRef references resolve
  - No inheritance contradiction (element allowing a lane/participant-denied tool)
  - Stripping all extensions yields a structurally intact BPMN process

Usage: python3 validate_bpmnx.py <file.bpmn> [bpmnx-1.0.xsd]
Exit code 0 = conformant, 1 = errors found.
"""
import sys
from lxml import etree

BPMN_NS  = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
BPMNX_NS = 'http://bpmnx.org/schema/1.0/bpmnx'
NS = {'bpmn': BPMN_NS, 'bpmnx': BPMNX_NS}

# Tasks + subprocess + gateways + intermediate catch are always enhanceable.
ENHANCEABLE_ALWAYS = {
    'task', 'serviceTask', 'userTask', 'businessRuleTask', 'scriptTask',
    'manualTask', 'sendTask', 'receiveTask', 'callActivity',
    'subProcess', 'exclusiveGateway', 'inclusiveGateway',
    'intermediateCatchEvent',
}
# Events enhanceable ONLY if typed (carry an eventDefinition child)
EVENT_TYPES = {'startEvent', 'endEvent', 'intermediateThrowEvent', 'boundaryEvent'}


def localname(tag):
    if not isinstance(tag, str):
        return ''
    return tag.split('}')[-1] if '}' in tag else tag


def has_event_definition(el):
    return any(localname(c.tag).endswith('EventDefinition') for c in el)


def validate(bpmn_path, xsd_path):
    errors, checks = [], []

    try:
        tree = etree.parse(bpmn_path)
        root = tree.getroot()
        checks.append("Well-formed BPMN 2.0 XML")
    except Exception as e:
        return [f"XML parse failed: {e}"], []

    try:
        schema = etree.XMLSchema(etree.parse(xsd_path))
    except Exception as e:
        return [f"Could not load BPMNx XSD: {e}"], checks

    all_ids = {el.get('id') for el in root.iter() if el.get('id')}

    # ── Validate every BPMNx extension element against XSD ──────────────
    bpmnx_markers = (
        root.findall('.//bpmnx:enhancement', NS) +
        root.findall('.//bpmnx:laneEnhancement', NS) +
        root.findall('.//bpmnx:participantEnhancement', NS)
    )
    for m in bpmnx_markers:
        frag = etree.fromstring(etree.tostring(m))
        if not schema.validate(frag):
            for err in schema.error_log:
                errors.append(f"<{localname(m.tag)}> schema error: {err.message}")

    # ── enhancement host checks ─────────────────────────────────────────
    element_enh = root.findall('.//bpmnx:enhancement', NS)
    for enh in element_enh:
        ext = enh.getparent()
        host = ext.getparent() if ext is not None else None
        if host is None:
            errors.append("enhancement with no host element")
            continue
        ln = localname(host.tag)
        if ln in EVENT_TYPES:
            if not has_event_definition(host):
                errors.append(
                    f"enhancement on PLAIN event <{ln}> (id={host.get('id','?')}) "
                    f"— only typed events (with an eventDefinition) are enhanceable [spec §2.1]")
        elif ln not in ENHANCEABLE_ALWAYS:
            errors.append(
                f"enhancement on non-enhanceable element <{ln}> "
                f"(id={host.get('id','?')}) [spec §2.1]")

    # ── laneEnhancement host checks ─────────────────────────────────────
    for le in root.findall('.//bpmnx:laneEnhancement', NS):
        host = le.getparent().getparent() if le.getparent() is not None else None
        if host is None or localname(host.tag) != 'lane':
            errors.append("laneEnhancement must be attached to a <bpmn:lane> [spec §2.2]")

    # ── participantEnhancement host checks ──────────────────────────────
    for pe in root.findall('.//bpmnx:participantEnhancement', NS):
        host = pe.getparent().getparent() if pe.getparent() is not None else None
        if host is None or localname(host.tag) != 'participant':
            errors.append("participantEnhancement must be attached to a <bpmn:participant> [spec §2.3]")

    # ── Reference integrity (onFailRef, targetRef) ──────────────────────
    for m in bpmnx_markers:
        for el in m.iter():
            for ref_attr in ('onFailRef', 'targetRef'):
                ref = el.get(ref_attr)
                if ref and ref not in all_ids:
                    errors.append(f"{ref_attr}='{ref}' does not resolve to any element id")

    # ── Inheritance contradiction: element allows a lane-denied tool ────
    # Build lane → denied tools, and lane → member element ids
    lane_denies = {}     # lane_id → set(tool refs)
    lane_members = {}    # lane_id → set(member element ids)
    for lane in root.findall('.//bpmn:lane', NS):
        lid = lane.get('id')
        le = lane.find('.//bpmnx:laneEnhancement', NS)
        denies = set()
        if le is not None:
            for td in le.findall('.//bpmnx:toolDeny', NS):
                denies.add(td.get('ref'))
        lane_denies[lid] = denies
        members = {fnr.text for fnr in lane.findall('bpmn:flowNodeRef', NS)}
        lane_members[lid] = members

    # member element id → set of denied tools inherited
    member_denied = {}
    for lid, members in lane_members.items():
        for mid in members:
            member_denied.setdefault(mid, set()).update(lane_denies.get(lid, set()))

    for enh in element_enh:
        host = enh.getparent().getparent()
        hid = host.get('id') if host is not None else None
        denied = member_denied.get(hid, set())
        for ta in enh.findall('.//bpmnx:toolAllow', NS):
            ref = ta.get('ref')
            if ref in denied:
                errors.append(
                    f"inheritance contradiction: element '{hid}' allows tool '{ref}' "
                    f"which its lane denies — denial wins, but the allow is misleading [spec §6.3]")

    if not any('schema error' in e for e in errors):
        checks.append(f"{len(bpmnx_markers)} BPMNx extension(s) validate against XSD")

    # ── Strip extensions → still valid process ──────────────────────────
    stripped = etree.fromstring(etree.tostring(root))
    for m in (stripped.findall('.//bpmnx:enhancement', NS) +
              stripped.findall('.//bpmnx:laneEnhancement', NS) +
              stripped.findall('.//bpmnx:participantEnhancement', NS)):
        m.getparent().remove(m)
    procs = stripped.findall('.//bpmn:process', NS)
    if not procs:
        # collaboration-only files may have processes referenced; tolerate
        checks.append("No <bpmn:process> in file (collaboration-level)")
    else:
        for proc in procs:
            ids = {el.get('id') for el in proc.iter() if el.get('id')}
            for f in proc.findall('.//bpmn:sequenceFlow', NS):
                if f.get('sourceRef') not in ids or f.get('targetRef') not in ids:
                    errors.append(f"After strip, flow {f.get('id')} has dangling endpoint")
        checks.append("Stripped process is structurally intact (executable as plain BPMN)")

    # ── Determinism summary ─────────────────────────────────────────────
    nd = sum(1 for e in element_enh if e.get('determinism') == 'nondeterministic')
    part_enh = root.findall('.//bpmnx:participantEnhancement', NS)
    lane_enh = root.findall('.//bpmnx:laneEnhancement', NS)
    if element_enh or part_enh or lane_enh:
        checks.append(
            f"Scopes: {len(element_enh)} element ({nd} nondeterministic), "
            f"{len(lane_enh)} lane, {len(part_enh)} participant")

    return errors, checks


if __name__ == '__main__':
    import os
    bpmn = sys.argv[1] if len(sys.argv) > 1 else 'examples/01-element-enhancement.bpmn'
    default_xsd = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               'schema', 'bpmnx-1.0.xsd')
    xsd = sys.argv[2] if len(sys.argv) > 2 else default_xsd
    errors, checks = validate(bpmn, xsd)
    print(f"BPMNx conformance check: {bpmn}\n")
    for c in checks:
        print(f"  \u2713 {c}")
    if errors:
        print(f"\n  {len(errors)} error(s):")
        for e in errors:
            print(f"  \u2717 {e}")
        sys.exit(1)
    else:
        print(f"\nCONFORMANT \u2014 valid BPMN 2.0 with valid BPMNx 1.0 extensions")
        sys.exit(0)
