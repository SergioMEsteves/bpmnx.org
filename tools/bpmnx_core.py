"""BPMNx core: parser, §6 policy engine and §7 validator (Python reference).

This module is a line-for-line port of the engine inside the BPMNx Bench
(bench/index.html). The Bench is the authoritative implementation; this port
exists so the same rules can run headless (CLI, CI). tests/parity.mjs runs the
Bench engine and this module over every example and fails if they disagree.

Diagnostic codes are identical between the two implementations. The Python
side adds two codes the Bench does not emit: E-XML (unparseable file) and
E-SCHEMA (a BPMNx marker fails XSD validation).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

from lxml import etree

BPMN = 'http://www.omg.org/spec/BPMN/20100524/MODEL'
DI = 'http://www.omg.org/spec/BPMN/20100524/DI'
NS10 = 'http://bpmnx.org/schema/1.0/bpmnx'
NS11 = 'http://bpmnx.org/schema/1.1/bpmnx'
NS_VERSION = {NS10: '1.0', NS11: '1.1'}
CURRENT_VERSION = '1.1'

TASK_TYPES = {'task', 'serviceTask', 'userTask', 'businessRuleTask', 'scriptTask',
              'sendTask', 'receiveTask', 'manualTask', 'callActivity'}
SUBPROC_TYPES = {'subProcess', 'transaction', 'adHocSubProcess'}
HUMAN_TYPES = {'userTask', 'manualTask'}
ENH_GATEWAYS = {'exclusiveGateway', 'inclusiveGateway'}
FLOW_LOCALS = TASK_TYPES | SUBPROC_TYPES | {
    'exclusiveGateway', 'inclusiveGateway', 'parallelGateway', 'eventBasedGateway',
    'complexGateway', 'startEvent', 'endEvent', 'intermediateCatchEvent',
    'intermediateThrowEvent', 'boundaryEvent'}

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XSD_FOR_NS = {
    NS10: os.path.join(REPO_ROOT, 'schema', 'bpmnx-1.0.xsd'),
    NS11: os.path.join(REPO_ROOT, 'schema', 'bpmnx-1.1.xsd'),
}

_DUR = re.compile(r'^(-)?P(?:(\d+(?:\.\d+)?)Y)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)W)?'
                  r'(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?'
                  r'(?:(\d+(?:\.\d+)?)S)?)?$')
NAN = float('nan')


def duration_to_seconds(d):
    """ISO-8601 duration -> seconds (approximate: Y=365d, M=30d). NaN if invalid."""
    if d is None or d == '':
        return None
    m = _DUR.match(d.strip())
    if not m:
        return NAN
    f = lambda x: float(x or 0)
    s = (f(m[2]) * 31536000 + f(m[3]) * 2592000 + f(m[4]) * 604800 + f(m[5]) * 86400
         + f(m[6]) * 3600 + f(m[7]) * 60 + f(m[8]))
    return -s if m[1] == '-' else s


def _isnan(v):
    return isinstance(v, float) and v != v


def ln(el):
    t = el.tag
    return t.split('}')[-1] if isinstance(t, str) and '}' in t else (t if isinstance(t, str) else '')


def ns_of(el):
    t = el.tag
    return t[1:].split('}')[0] if isinstance(t, str) and t.startswith('{') else None


def kids(n, ns, local):
    return [c for c in n if isinstance(c.tag, str) and ns_of(c) == ns and ln(c) == local]


def kid(n, ns, local):
    k = kids(n, ns, local)
    return k[0] if k else None


def txt(n):
    return (''.join(n.itertext()).strip()) if n is not None else ''


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------

def parse_envelope(env):
    if env is None:
        return None
    e = dict(toolAllow=[], toolDeny=[], constraints=[], confidenceThreshold=None, confRaw=None,
             maxSteps=None, maxStepsRaw=None, timeBudget=None, retryPolicy=None,
             audited=False, irreversible=False, hasIrreversibleAttr=False)
    for t in kids(env, _BPMNX[0], 'toolAllow'):
        e['toolAllow'].append({'ref': t.get('ref'), 'label': txt(t)})
    for t in kids(env, _BPMNX[0], 'toolDeny'):
        e['toolDeny'].append({'ref': t.get('ref'), 'label': txt(t)})
    for c in kids(env, _BPMNX[0], 'constraint'):
        e['constraints'].append({'type': c.get('type'), 'text': txt(c)})
    ct = env.get('confidenceThreshold')
    if ct is not None:
        e['confRaw'] = ct
        try:
            e['confidenceThreshold'] = float(ct)
        except ValueError:
            e['confidenceThreshold'] = NAN
    ms = env.get('maxSteps')
    if ms is not None:
        e['maxStepsRaw'] = ms
        mm = re.match(r'^\s*[-+]?\d+', ms)
        e['maxSteps'] = int(mm.group(0)) if mm else NAN
    e['timeBudget'] = env.get('timeBudget')
    e['retryPolicy'] = env.get('retryPolicy')
    e['audited'] = env.get('audited') == 'true'
    if env.get('irreversible') is not None:
        e['hasIrreversibleAttr'] = True
        e['irreversible'] = env.get('irreversible') == 'true'
    return e


# The active BPMNx namespace for the document being parsed (mirrors the Bench's
# module-level `BPMNX`, which is reassigned per document).
_BPMNX = [NS11]


def parse_agent(a):
    if a is None:
        return None
    X = _BPMNX[0]
    return dict(role=a.get('role'), modelClass=a.get('modelClass'),
                systemPrompt=txt(kid(a, X, 'systemPrompt')),
                inputContract=txt(kid(a, X, 'inputContract')),
                outputContract=txt(kid(a, X, 'outputContract')))


def parse_reviews(parent):
    out = []
    for r in kids(parent, _BPMNX[0], 'review'):
        mr = r.get('maxRetries')
        try:
            mr = int(mr) if mr is not None else 2
        except ValueError:
            mr = NAN
        out.append(dict(kind=r.get('kind'), maxRetries=mr, onFailRef=r.get('onFailRef'),
                        criteria=[txt(c) for c in kids(r, _BPMNX[0], 'criterion')]))
    return out


def parse_escalations(parent):
    return [dict(when=s.get('when'), targetRef=s.get('targetRef'), sla=s.get('sla'), text=txt(s))
            for s in kids(parent, _BPMNX[0], 'escalation')]


def parse_properties(parent):
    return [dict(name=p.get('name'), value=txt(p)) for p in kids(parent, _BPMNX[0], 'property')]


def get_enh_node(host, local):
    ext = kid(host, BPMN, 'extensionElements')
    return kid(ext, _BPMNX[0], local) if ext is not None else None


def parse_element_enh(n):
    X = _BPMNX[0]
    return dict(kind='element', version=n.get('version'), determinism=n.get('determinism'),
                hasDeterminism=n.get('determinism') is not None,
                agent=parse_agent(kid(n, X, 'agent')),
                envelope=parse_envelope(kid(n, X, 'envelope')),
                reviews=parse_reviews(n), escalations=parse_escalations(n),
                properties=parse_properties(n))


def parse_lane_enh(n):
    return dict(kind='lane', version=n.get('version'),
                envelope=parse_envelope(kid(n, _BPMNX[0], 'envelope')),
                properties=parse_properties(n))


def parse_participant_enh(n):
    X = _BPMNX[0]
    return dict(kind='participant', version=n.get('version'), determinism=n.get('determinism'),
                hasDeterminism=n.get('determinism') is not None,
                boundary=n.get('boundary') or 'blackBox',
                agent=parse_agent(kid(n, X, 'agent')),
                envelope=parse_envelope(kid(n, X, 'envelope')),
                reviews=parse_reviews(n), properties=parse_properties(n))


def collect_misattached(host, host_kind):
    ext = kid(host, BPMN, 'extensionElements')
    if ext is None:
        return []
    out = []
    for m in ('enhancement', 'laneEnhancement', 'participantEnhancement'):
        proper = (host_kind == 'participant' and m == 'participantEnhancement') or \
                 (host_kind == 'lane' and m == 'laneEnhancement')
        if not proper and kid(ext, _BPMNX[0], m) is not None:
            out.append(m)
    return out


@dataclass
class Model:
    ok: bool = True
    parseError: Optional[str] = None
    root: object = None
    bpmnxNs: str = NS11
    bpmnxVersion: str = CURRENT_VERSION
    legacy: bool = False
    mixedNs: bool = False
    nodes: dict = field(default_factory=dict)
    flows: dict = field(default_factory=dict)
    messageFlows: list = field(default_factory=list)
    lanes: dict = field(default_factory=dict)
    participants: dict = field(default_factory=dict)
    processes: dict = field(default_factory=dict)
    hasAnyBpmnx: bool = False


def detect_ns(root):
    has10 = any(ns_of(e) == NS10 for e in root.iter() if isinstance(e.tag, str))
    has11 = any(ns_of(e) == NS11 for e in root.iter() if isinstance(e.tag, str))
    return has10, has11


def parse_model(source) -> Model:
    m = Model()
    try:
        if isinstance(source, bytes):
            root = etree.fromstring(source)
        elif isinstance(source, str) and source.lstrip().startswith('<'):
            root = etree.fromstring(source.encode('utf-8'))
        else:
            root = etree.parse(source).getroot()
    except Exception as e:  # noqa: BLE001
        return Model(ok=False, parseError=str(e))
    if ln(root) != 'definitions':
        return Model(ok=False, parseError='Root element is not <bpmn:definitions>. Not a BPMN 2.0 document.')
    m.root = root
    has10, has11 = detect_ns(root)
    m.mixedNs = has10 and has11
    m.bpmnxNs = NS10 if (has10 and not has11) else NS11
    m.bpmnxVersion = NS_VERSION[m.bpmnxNs]
    m.legacy = m.bpmnxNs == NS10
    _BPMNX[0] = m.bpmnxNs

    for p in root.iter('{%s}participant' % BPMN):
        pid = p.get('id')
        part = dict(id=pid, name=p.get('name'), processRef=p.get('processRef'), enh=None, boundary=None)
        en = get_enh_node(p, 'participantEnhancement')
        if en is not None:
            part['enh'] = parse_participant_enh(en)
            part['boundary'] = part['enh']['boundary']
            m.hasAnyBpmnx = True
        part['_mis'] = collect_misattached(p, 'participant')
        m.participants[pid] = part
    for mf in root.iter('{%s}messageFlow' % BPMN):
        m.messageFlows.append(dict(id=mf.get('id'), name=mf.get('name'),
                                   sourceRef=mf.get('sourceRef'), targetRef=mf.get('targetRef')))

    for proc in root.iter('{%s}process' % BPMN):
        pid = proc.get('id')
        pobj = dict(id=pid, laneIds=[], nodeIds=[])
        m.processes[pid] = pobj

        # lanes (recursive through childLaneSet; record ancestry outer -> inner)
        def walk_laneset(ls, ancestors):
            for l in kids(ls, BPMN, 'lane'):
                lid = l.get('id')
                lane = dict(id=lid, name=l.get('name'), processId=pid,
                            flowNodeRefs=[txt(r) for r in kids(l, BPMN, 'flowNodeRef')],
                            enh=None, ancestors=list(ancestors), depth=len(ancestors))
                en = get_enh_node(l, 'laneEnhancement')
                if en is not None:
                    lane['enh'] = parse_lane_enh(en)
                    m.hasAnyBpmnx = True
                lane['_mis'] = collect_misattached(l, 'lane')
                m.lanes[lid] = lane
                pobj['laneIds'].append(lid)
                for cls in kids(l, BPMN, 'childLaneSet'):
                    walk_laneset(cls, ancestors + [lid])
        for ls in kids(proc, BPMN, 'laneSet'):
            walk_laneset(ls, [])

        for n in proc:
            if not isinstance(n.tag, str) or ns_of(n) != BPMN or ln(n) not in FLOW_LOCALS:
                continue
            nid = n.get('id')
            event_defs = [ln(c) for c in n if isinstance(c.tag, str) and ns_of(c) == BPMN
                          and ln(c).endswith('EventDefinition')]
            node = dict(id=nid, local=ln(n), name=n.get('name'), processId=pid, eventDefs=event_defs,
                        incoming=[txt(c) for c in kids(n, BPMN, 'incoming')],
                        outgoing=[txt(c) for c in kids(n, BPMN, 'outgoing')],
                        default=n.get('default'), attachedToRef=n.get('attachedToRef'),
                        enh=None, laneId=None, laneIds=[], participantId=None)
            en = get_enh_node(n, 'enhancement')
            if en is not None:
                node['enh'] = parse_element_enh(en)
                m.hasAnyBpmnx = True
            node['_misLane'] = get_enh_node(n, 'laneEnhancement') is not None
            node['_misPart'] = get_enh_node(n, 'participantEnhancement') is not None
            m.nodes[nid] = node
            pobj['nodeIds'].append(nid)

        for f in proc.iter('{%s}sequenceFlow' % BPMN):
            fid = f.get('id')
            m.flows[fid] = dict(id=fid, name=f.get('name'), sourceRef=f.get('sourceRef'),
                                targetRef=f.get('targetRef'), processId=pid,
                                enh=get_enh_node(f, 'enhancement') is not None,
                                condition=txt(kid(f, BPMN, 'conditionExpression')) or None)

    # node -> innermost lane, and the full lane chain outer -> inner
    for lane in m.lanes.values():
        for ref in lane['flowNodeRefs']:
            n = m.nodes.get(ref)
            if n is None:
                continue
            cur = m.lanes.get(n['laneId']) if n['laneId'] else None
            if cur is None or lane['depth'] >= cur['depth']:
                n['laneId'] = lane['id']
    for n in m.nodes.values():
        if n['laneId']:
            n['laneIds'] = m.lanes[n['laneId']]['ancestors'] + [n['laneId']]
    for part in m.participants.values():
        proc = m.processes.get(part['processRef'])
        if proc:
            for nid in proc['nodeIds']:
                m.nodes[nid]['participantId'] = part['id']
    return m


# --------------------------------------------------------------------------
# §6 policy engine
# --------------------------------------------------------------------------

def scope_chain(m: Model, node):
    chain = []
    if node.get('participantId'):
        p = m.participants.get(node['participantId'])
        if p and p['enh'] and p['boundary'] == 'whiteBox' and p['enh']['envelope']:
            chain.append(dict(scope='participant', env=p['enh']['envelope'], owner=p['id']))
    for lid in node.get('laneIds') or []:
        l = m.lanes.get(lid)
        if l and l['enh'] and l['enh']['envelope']:
            chain.append(dict(scope='lane', env=l['enh']['envelope'], owner=lid))
    if node.get('enh'):
        env = node['enh']['envelope'] or dict(toolAllow=[], toolDeny=[], constraints=[])
        chain.append(dict(scope='element', env=env, owner=node['id']))
    return chain


def effective_policy(m: Model, node):
    chain = scope_chain(m, node)
    deny, allow, constraints = {}, {}, []
    conf = dict(val=None, frm='none')
    steps = dict(val=None, frm='none')
    time = dict(val=None, secs=None, frm='none')
    retry = dict(val=None, frm='none')
    audited = dict(val=False, frm='none')
    irrev = dict(val=False, frm='none')
    for link in chain:
        e, sc = link['env'] or {}, link['scope']
        for t in e.get('toolDeny', []):
            if t['ref'] and t['ref'] not in deny:
                deny[t['ref']] = sc
        for t in e.get('toolAllow', []):
            if t['ref'] and t['ref'] not in allow:
                allow[t['ref']] = sc
        for c in e.get('constraints', []):
            constraints.append(dict(c, frm=sc))
        ct = e.get('confidenceThreshold')
        if ct is not None and not _isnan(ct) and (conf['val'] is None or ct > conf['val']):
            conf = dict(val=ct, frm=sc)
        ms = e.get('maxSteps')
        if ms is not None and not _isnan(ms) and (steps['val'] is None or ms < steps['val']):
            steps = dict(val=ms, frm=sc)
        if e.get('timeBudget') is not None:
            s = duration_to_seconds(e['timeBudget'])
            if not _isnan(s) and (time['secs'] is None or s < time['secs']):
                time = dict(val=e['timeBudget'], secs=s, frm=sc)
        if e.get('retryPolicy') is not None:
            retry = dict(val=e['retryPolicy'], frm=sc)
        if e.get('audited') is True and not audited['val']:
            audited = dict(val=True, frm=sc)
        if sc == 'element' and e.get('irreversible') is True:
            irrev = dict(val=True, frm='element')
    allowed, overridden = [], []
    for ref, sc in allow.items():
        if ref in deny:
            overridden.append(dict(ref=ref, allowedBy=sc, deniedBy=deny[ref]))
        else:
            allowed.append(dict(ref=ref, frm=sc))
    return dict(chain=chain, toolDeny=[dict(ref=r, frm=s) for r, s in deny.items()],
                toolAllow=allowed, overridden=overridden, constraints=constraints,
                confidenceThreshold=conf, maxSteps=steps, timeBudget=time,
                retryPolicy=retry, audited=audited, irreversible=irrev)


# --------------------------------------------------------------------------
# helpers shared with the Bench
# --------------------------------------------------------------------------

def reachable_from(m: Model, node):
    """Ids reachable from `node` by sequence flow, starting from its outgoing flows
    and from any boundary event attached to it (§4.3)."""
    starts = [m.flows[f]['targetRef'] for f in node['outgoing'] if f in m.flows]
    for b in m.nodes.values():
        if b['local'] == 'boundaryEvent' and b['attachedToRef'] == node['id']:
            starts.append(b['id'])
    seen, stack = set(), list(starts)
    while stack:
        nid = stack.pop()
        if nid in seen or nid not in m.nodes:
            continue
        seen.add(nid)
        for f in m.nodes[nid]['outgoing']:
            fl = m.flows.get(f)
            if fl:
                stack.append(fl['targetRef'])
    return seen


_OUTCOME_RE = re.compile(r'^\s*([A-Za-z0-9_.-]+(?:\s*\|\s*[A-Za-z0-9_.-]+)+)')


def gateway_outcomes(contract):
    """Outcomes declared by an outputContract of the form 'a | b | c[, ...]'."""
    if not contract:
        return []
    mm = _OUTCOME_RE.match(contract)
    if not mm:
        return []
    return [s.strip() for s in mm.group(1).split('|') if s.strip()]


# --------------------------------------------------------------------------
# §7 validator
# --------------------------------------------------------------------------

def validate(m: Model):
    out = []
    E = lambda code, msg, ref: out.append(dict(severity='error', code=code, message=msg, ref=ref))
    W = lambda code, msg, ref: out.append(dict(severity='warning', code=code, message=msg, ref=ref))
    V = m.bpmnxVersion

    def host_ok(n):
        if n['local'] in TASK_TYPES or n['local'] in SUBPROC_TYPES:
            return True
        if n['local'] in ENH_GATEWAYS:
            return True
        if n['local'] == 'intermediateCatchEvent':
            return True
        if n['local'] in ('startEvent', 'endEvent', 'boundaryEvent'):
            return len(n['eventDefs']) > 0
        return False

    def disallowed_reason(n):
        if n['local'] in ('startEvent', 'endEvent', 'boundaryEvent'):
            return f"a plain {n['local']} (no eventDefinition) carries no judgment to bound (§2.1)"
        if n['local'] in ('parallelGateway', 'eventBasedGateway', 'complexGateway'):
            return f"a {n['local']} is not an enhanceable host; only exclusive/inclusive gateways are (§2.1)"
        if n['local'] == 'intermediateThrowEvent':
            return 'an intermediateThrowEvent emits a signal; there is no judgment to bound (§2.1)'
        return f"{n['local']} is not an enhanceable host (§2.1)"

    if m.mixedNs:
        E('E-NS-MIXED', 'Document mixes the BPMNx 1.0 and 1.1 namespaces. Use one namespace per document (§9).', None)
    if m.legacy:
        W('W-LEGACY-NS', 'Document uses the BPMNx 1.0 namespace. It is checked under 1.1 rules; '
          'migrate with tools/migrate_1_0_to_1_1.py (§9).', None)

    for node in m.nodes.values():
        if node['_misLane']:
            E('E-SCOPE-HOST', f"laneEnhancement is attached to <{node['local']}>; it may only attach to a bpmn:lane (§2.2).", node['id'])
        if node['_misPart']:
            E('E-SCOPE-HOST', f"participantEnhancement is attached to <{node['local']}>; it may only attach to a bpmn:participant (§2.3).", node['id'])
        if not node['enh']:
            continue
        enh, ref = node['enh'], node['id']
        where = f'"{node["name"]}"' if node['name'] else node['id']
        is_ai = enh['determinism'] == 'nondeterministic'

        if not host_ok(node):
            E('E-HOST', f'enhancement on {where} is invalid: {disallowed_reason(node)}.', ref)
        if enh['version'] != V:
            E('E-VERSION', f'enhancement on {where} has version="{enh["version"]}"; BPMNx {V} fixes it to "{V}".', ref)
        if not enh['hasDeterminism']:
            E('E-DET-MISSING', f'enhancement on {where} is missing the required determinism attribute (§3.1).', ref)
        elif enh['determinism'] not in ('deterministic', 'nondeterministic'):
            E('E-DET-ENUM', f'determinism="{enh["determinism"]}" on {where} is not deterministic|nondeterministic.', ref)
        if enh['agent'] and not enh['agent']['role']:
            E('E-AGENT-ROLE', f'agent on {where} is missing the required role attribute.', ref)

        validate_envelope(enh['envelope'], 'element', where, ref, E, W)

        reach = None
        for i, r in enumerate(enh['reviews']):
            if r['kind'] not in ('critic', 'adversary'):
                E('E-REVIEW-KIND', f'review #{i+1} on {where} has kind="{r["kind"]}"; must be critic|adversary (§4).', ref)
            if not r['criteria']:
                E('E-REVIEW-CRIT', f'review #{i+1} on {where} declares no <criterion> (at least one required).', ref)
            if r['onFailRef'] and r['onFailRef'] not in m.nodes:
                E('E-ONFAILREF', f'review onFailRef="{r["onFailRef"]}" on {where} does not resolve to an element id (§7.1).', ref)
            elif r['onFailRef']:
                reach = reach if reach is not None else reachable_from(m, node)
                if r['onFailRef'] not in reach:
                    E('E-REF-UNREACHABLE', f'review onFailRef="{r["onFailRef"]}" on {where} is not reachable by sequence flow from the element or a boundary event attached to it (§4.3).', ref)
            if not _isnan(r['maxRetries']) and r['maxRetries'] < 0:
                E('E-MAXRETRIES', f'review maxRetries on {where} must be ≥ 0.', ref)
        for i, s in enumerate(enh['escalations']):
            if not s['when']:
                E('E-ESCAL-WHEN', f'escalation #{i+1} on {where} is missing the required when attribute (§4).', ref)
            if s['targetRef'] and s['targetRef'] not in m.nodes:
                E('E-TARGETREF', f'escalation targetRef="{s["targetRef"]}" on {where} does not resolve to an element id (§7.1).', ref)
            elif s['targetRef']:
                reach = reach if reach is not None else reachable_from(m, node)
                if s['targetRef'] not in reach:
                    E('E-REF-UNREACHABLE', f'escalation targetRef="{s["targetRef"]}" on {where} is not reachable by sequence flow from the element or a boundary event attached to it (§4.3).', ref)
            if s['sla'] and _isnan(duration_to_seconds(s['sla'])):
                E('E-SLA', f'escalation sla="{s["sla"]}" on {where} is not an ISO-8601 duration.', ref)

        pol = effective_policy(m, node)
        for o in pol['overridden']:
            E('E-CONTRADICTION', f'on {where}, tool "{o["ref"]}" is allowed at the {o["allowedBy"]} scope but denied at the {o["deniedBy"]} scope. The merge resolves safely (denial wins) but §6.3 requires this contradiction be flagged.', ref)

        if pol['irreversible']['val']:
            preds = [m.nodes.get(m.flows[f]['sourceRef']) for f in node['incoming'] if f in m.flows]
            succs = [m.nodes.get(m.flows[f]['targetRef']) for f in node['outgoing'] if f in m.flows]
            human_pred = any(p and p['local'] in HUMAN_TYPES for p in preds)
            human_succ = any(s and s['local'] in HUMAN_TYPES for s in succs)
            if human_pred:
                pass
            elif human_succ:
                W('W-IRREV-AFTER', f'irreversible action {where} is followed by a human-controlled element but not preceded by one. Approval must come before the side effect — place the human gate upstream (§5.1, §7.1).', ref)
            else:
                E('E-IRREV-NOHUMAN', f'irreversible action {where} is not immediately preceded by a human-controlled element (userTask/manualTask) to gate it (§5.1, §7.1).', ref)

        if node['local'] in ENH_GATEWAYS and is_ai and enh['agent']:
            outcomes = gateway_outcomes(enh['agent']['outputContract'])
            if outcomes:
                outs = [m.flows[f] for f in node['outgoing'] if f in m.flows]
                names = {(f['name'] or '').strip().lower() for f in outs if f['name']}
                low = {o.lower() for o in outcomes}
                for o in outcomes:
                    if o.lower() not in names:
                        W('W-GW-OUTCOME', f'gateway {where} can return "{o}" but no outgoing flow is named "{o}"; that outcome has nowhere to go (§4.4).', ref)
                for f in outs:
                    if f['name'] and f['name'].strip().lower() not in low and f['id'] != node['default']:
                        W('W-GW-FLOW', f'outgoing flow "{f["name"]}" of gateway {where} matches no outcome in its outputContract (§4.4).', ref)

    for lane in m.lanes.values():
        lname = lane['name'] or lane['id']
        for mk in lane['_mis']:
            E('E-SCOPE-HOST', f'<{mk}> is attached to lane "{lname}"; a lane may only carry laneEnhancement (§2.2).', lane['id'])
        if not lane['enh']:
            continue
        if lane['enh']['version'] != V:
            E('E-VERSION', f'laneEnhancement on "{lname}" has version="{lane["enh"]["version"]}"; must be "{V}".', lane['id'])
        validate_envelope(lane['enh']['envelope'], 'scope', f'lane "{lname}"', lane['id'], E, W)

    for part in m.participants.values():
        pname = part['name'] or part['id']
        for mk in part['_mis']:
            E('E-SCOPE-HOST', f'<{mk}> is attached to participant "{pname}"; a participant may only carry participantEnhancement (§2.3).', part['id'])
        if not part['enh']:
            continue
        p, where = part['enh'], f'participant "{pname}"'
        if p['version'] != V:
            E('E-VERSION', f'participantEnhancement on {where} has version="{p["version"]}"; must be "{V}".', part['id'])
        if not p['hasDeterminism']:
            E('E-DET-MISSING', f'participantEnhancement on {where} is missing the required determinism attribute (§3.1).', part['id'])
        if p['boundary'] not in ('blackBox', 'whiteBox'):
            E('E-BOUNDARY', f'boundary="{p["boundary"]}" on {where} must be blackBox|whiteBox.', part['id'])
        if p['agent'] and not p['agent']['role']:
            E('E-AGENT-ROLE', f'agent on {where} is missing role.', part['id'])
        validate_envelope(p['envelope'], 'scope', where, part['id'], E, W)
        if p['boundary'] == 'whiteBox':
            proc = m.processes.get(part['processRef'])
            if not proc or not proc['nodeIds']:
                W('W-WHITEBOX-EMPTY', f'{where} is whiteBox but its processRef resolves to no modeled flow (§6.4).', part['id'])

    for f in m.flows.values():
        if f['enh']:
            E('E-HOST', f'enhancement is attached to sequenceFlow "{f["id"]}"; sequence flows are not enhanceable (§2.1).', f['id'])
    for f in m.flows.values():
        if f['sourceRef'] and f['sourceRef'] not in m.nodes:
            W('W-FLOW-REF', f'sequenceFlow {f["id"]} sourceRef {f["sourceRef"]} not found.', f['id'])
        if f['targetRef'] and f['targetRef'] not in m.nodes:
            W('W-FLOW-REF', f'sequenceFlow {f["id"]} targetRef {f["targetRef"]} not found.', f['id'])

    if not m.hasAnyBpmnx:
        W('W-NO-BPMNX', 'No BPMNx extensions found. This is a plain BPMN 2.0 document — valid, but nothing is agent-operated.', None)

    if not any(o['severity'] == 'error' for o in out):
        out.insert(0, dict(severity='ok', code='CONFORMANT', ref=None,
                           message='No conformance errors.'))
    return out


def validate_envelope(env, kind, where, ref, E, W):
    if not env:
        return
    if kind == 'scope' and env['hasIrreversibleAttr']:
        E('E-IRREV-SCOPE', f'envelope on {where} carries irreversible; irreversibility is a property of a concrete action and is not permitted on a scope (lane/participant) envelope (§5.2).', ref)
    if env['confRaw'] is not None:
        try:
            v = float(env['confRaw'])
        except ValueError:
            v = NAN
        if _isnan(v) or v < 0 or v > 1:
            E('E-CONF-RANGE', f'confidenceThreshold="{env["confRaw"]}" on {where} is outside [0,1].', ref)
    if env['maxStepsRaw'] is not None:
        try:
            v = float(env['maxStepsRaw'])
            ok = v.is_integer() and v >= 1
        except ValueError:
            ok = False
        if not ok:
            E('E-MAXSTEPS', f'maxSteps="{env["maxStepsRaw"]}" on {where} must be a positive integer.', ref)
    if env['timeBudget'] is not None and _isnan(duration_to_seconds(env['timeBudget'])):
        E('E-TIMEBUDGET', f'timeBudget="{env["timeBudget"]}" on {where} is not an ISO-8601 duration.', ref)
    for t in env['toolAllow'] + env['toolDeny']:
        if not t['ref']:
            E('E-TOOL-REF', f'a tool element on {where} is missing the required ref attribute.', ref)


# --------------------------------------------------------------------------
# XSD check (Python-only extra)
# --------------------------------------------------------------------------

_schema_cache = {}


def schema_check(m: Model):
    out = []
    if not m.ok:
        return out
    xsd = XSD_FOR_NS.get(m.bpmnxNs)
    if xsd not in _schema_cache:
        _schema_cache[xsd] = etree.XMLSchema(etree.parse(xsd))
    schema = _schema_cache[xsd]
    for local in ('enhancement', 'laneEnhancement', 'participantEnhancement'):
        for mk in m.root.iter('{%s}%s' % (m.bpmnxNs, local)):
            host = mk.getparent().getparent() if mk.getparent() is not None else None
            frag = etree.fromstring(etree.tostring(mk))
            if not schema.validate(frag):
                for err in schema.error_log:
                    out.append(dict(severity='error', code='E-SCHEMA',
                                    ref=host.get('id') if host is not None else None,
                                    message=f'<{local}> fails the BPMNx {m.bpmnxVersion} XSD: {err.message}'))
    return out


def check_file(path):
    m = parse_model(path)
    if not m.ok:
        return m, [dict(severity='error', code='E-XML', ref=None, message=m.parseError)]
    diags = validate(m)
    extra = schema_check(m)
    if extra:
        diags = [d for d in diags if d['code'] != 'CONFORMANT'] + extra
    return m, diags
