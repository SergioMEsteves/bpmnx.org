# BPMNx 1.1 — Specification

**Status:** Draft Standard
**Namespace:** `http://bpmnx.org/schema/1.1/bpmnx`
**Conventional prefix:** `bpmnx`
**Schema:** [`schema/bpmnx-1.1.xsd`](../schema/bpmnx-1.1.xsd)
**Reference implementation:** the BPMNx Bench ([`bench/index.html`](../bench/index.html)).
Where this text and the Bench disagree, the Bench is authoritative and the
text is a bug. Changes from 1.0 are listed in §10.

BPMNx is an open extension to the OMG BPMN 2.0 standard for modeling agentic
AI workflows. It defines a vocabulary, carried inside the standard
`<bpmn:extensionElements>` container, for declaring that parts of a process
are operated by agents and for specifying the guardrails that bound them.

A BPMNx document **is** a BPMN 2.0 document. It opens, renders, and executes in
any conformant BPMN 2.0 tool. Tools that do not understand BPMNx ignore the
extension namespace and process the file as ordinary BPMN. Tools that do
understand BPMNx read the extensions and operate the marked parts through an
agent under the declared constraints.

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, and MAY in this
document are to be interpreted as described in RFC 2119.

---

## 1. Design principles

1. **Additive, never destructive.** BPMNx adds metadata inside the BPMN-
   sanctioned extension point. It never redefines BPMN elements, alters
   sequence flow, changes token semantics, or touches the meaning of pools
   and lanes. Removing all BPMNx extensions from a conformant file MUST
   always yield a valid, executable BPMN 2.0 process.

2. **One marker per scope.** Each scope has exactly one extension element:
   `enhancement` (element scope), `laneEnhancement` (lane scope),
   `participantEnhancement` (participant scope). Presence of the marker is
   the single signal that something is agent-operated.

3. **Inert without a runtime.** The extension is metadata. It describes intent
   and constraints; it does not itself execute anything. Value is realized by
   a BPMNx-aware runtime. The schema and this specification are the open
   standard; runtimes that interpret them are implementation concerns.

4. **Determinism is explicit and machine-readable.** Every element- and
   participant-scope enhancement declares `determinism`. Agent-operated is
   not the same as AI-decided: an agent may drive a deterministic program as
   a tool. Which parts of a process involve model judgment is a queryable
   fact, not merely a visual cue (§3.3).

6. **Every route is drawn.** Every path the guardrails can take — an
   escalation, a review's terminal failure, each outcome of an AI gateway —
   is a sequence flow on the diagram. A reader of the diagram alone sees
   every way the process can go (§4.3, §4.4).

5. **Guardrails only ratchet tighter.** When policy is inherited from a
   broader scope (lane, participant) to a narrower one (element), the narrower
   scope MAY tighten a guardrail but MUST NOT loosen it. This single rule is
   what makes a scope-level envelope a trustworthy safety boundary. See §6.

---

## 2. The three scopes of enhancement

BPMNx recognizes that agents show up in real workflows at three different scopes.

### 2.1 Element scope — `<bpmnx:enhancement>`

A single BPMN element is agent-operated. Attach to the `extensionElements` of:

| BPMN element                                            | Enhanceable because                       |
|---------------------------------------------------------|-------------------------------------------|
| `task` and subtypes (service, user, business rule, …)   | the agent performs the unit of work       |
| `subProcess`                                            | the agent orchestrates a bounded scope    |
| `exclusiveGateway`, `inclusiveGateway`                  | the agent evaluates the routing decision  |
| `intermediateCatchEvent`                                | the agent judges whether a condition holds |
| **typed** `startEvent` (carries an `eventDefinition`)   | the agent judges whether to start         |
| **typed** `endEvent` (carries an `eventDefinition`)     | the agent composes/decides the terminus   |
| **typed** `boundaryEvent` (carries an `eventDefinition`) | the agent judges whether the interrupting/non-interrupting condition has occurred |

A **typed** event is one carrying a child `eventDefinition` (message,
conditional, signal, error, etc.). A *plain* start, end or boundary event — a
bare token source or sink with no event definition — is NOT enhanceable: there
is no judgment to bound. A conformant validator MUST reject an `enhancement`
on a plain event.

Enhancement MUST NOT be attached to: `sequenceFlow`, `lane`, `participant`
(those have their own scope markers), `dataObject`, `textAnnotation`,
`intermediateThrowEvent` (it emits a signal; there is no judgment to bound),
`parallelGateway`, `eventBasedGateway`, or a plain event.

### 2.2 Lane scope — `<bpmnx:laneEnhancement>`

A lane declares shared guardrails inherited by every enhanced element it
contains. A lane is not itself "operated" — it is an ownership band — but it
is the natural place to declare guardrails common to all AI work in that band
(for example: "nothing in the AI lane may ever send email; everything here is
audited"). This realizes the "constraint envelope" concept anchored to a real
BPMN structural element rather than as a free-floating overlay.

Attach to the `extensionElements` of a `bpmn:lane`. Lane membership is
determined by BPMN's own `bpmn:flowNodeRef` children of the lane. Lanes may
nest through `bpmn:childLaneSet`; every enclosing lane that carries an
envelope is in the element's scope chain (§6.1). The lane
envelope is a **scope envelope** (§5.2): it has no `irreversible` attribute,
because irreversibility is a property of a concrete action.

### 2.3 Participant scope — `<bpmnx:participantEnhancement>`

An entire participant (pool) is an agentic system. The canonical case is a
**black-box pool**: a counterparty whose internals are an agent's reasoning
you do not model, with which your process collaborates by exchanging messages
(for example, "the AI underwriting service"). This is a distinct and more
powerful concept than element-level enhancement: it declares that a whole
participant in a collaboration is an agentic system, with its own
participant-scope envelope.

Attach to the `extensionElements` of a `bpmn:participant`. The `boundary`
attribute records whether the participant is `blackBox` (internals not
modeled) or `whiteBox` (the pool contains a modeled process). For a whiteBox
participant, the participant envelope behaves as an additional outer scope in
the inheritance chain (§6.4).

---

## 3. The `<bpmnx:enhancement>` element (element scope)

### 3.1 Attributes

| Attribute     | Required | Meaning                                  |
|---------------|----------|------------------------------------------|
| `version`     | yes      | BPMNx schema version. Fixed `"1.1"`.     |
| `determinism` | yes      | `deterministic` or `nondeterministic` (§3.3). |

### 3.2 Child elements (all optional, in document order)

- **`<agent>`** — the AI agent: logical `role`, optional `modelClass` hint,
  and optional `systemPrompt`, `inputContract`, `outputContract`.
- **`<envelope>`** — the element constraint envelope (§5.1).
- **`<review>`** (repeatable) — a verification pass (§4).
- **`<escalation>`** (repeatable) — a human-handoff condition (§4).
- **`<property>`** (repeatable) — free-form key/value metadata.

### 3.3 Determinism: AI and Program

`determinism` classifies **how the element's outcome is produced**, not
whether an agent is involved. Both kinds are enhanced and both are bound by
an envelope.

| `determinism`      | Category    | Meaning |
|--------------------|-------------|---------|
| `nondeterministic` | **AI**      | The outcome is produced by model judgment and may differ between runs on identical input. |
| `deterministic`    | **Program** | The element is operated by an agent, but its outcome is produced by fixed logic the agent invokes as a tool — for example a deterministic RAG retrieval backend, a rules engine, or a ledger API. Identical input yields identical output. |

Why enhance a Program element at all: so its tool allowances, denials,
constraints, audit and irreversibility are declared and inherited exactly
like an AI element's. `confidenceThreshold`, `maxSteps`, `<agent>`
and `<review>` are meaningful only for AI elements; a Program element MAY
omit them.

---

## 4. Reviews and escalations

A **`<review kind="critic">`** checks the element's output against its
contract (conformance). A **`<review kind="adversary">`** stress-tests the
output for silent failure on the happy path. The two are always distinct
reviews; a conformant document MUST NOT merge them into one. Each review
carries one or more `<criterion>`, an optional `maxRetries` (default 2), and
an optional `onFailRef` pointing to the BPMN element that handles terminal
failure. A conformant runtime MUST run declared reviews before the element's
output is consumed downstream, and MUST route to `onFailRef` after
`maxRetries` failures.

An **`<escalation>`** declares a condition (`when`) under which the agent MUST
hand control to a human, with an optional `targetRef` (the handling element)
and `sla` (ISO 8601 duration).

### 4.3 Routes are drawn

Every `onFailRef` and `targetRef` MUST name an element reachable by sequence
flow from the enhanced element — through its outgoing flows, or through a
typed `boundaryEvent` attached to it. The idiomatic form is a boundary event
on the element (an `escalationEventDefinition` for an escalation, an
`errorEventDefinition` for a review's terminal failure) with a sequence flow
to the handler. A reference to an element that exists but cannot be reached
is an error (`E-REF-UNREACHABLE`): the diagram would hide a route the
runtime takes.

### 4.4 AI gateway outcomes

When an AI (`nondeterministic`) exclusive or inclusive gateway declares an
`outputContract` of the form `a | b | c` (optionally followed by `,` and
prose), each listed outcome is a routing answer. Each outcome SHOULD have an
outgoing sequence flow whose `name` equals it (case-insensitive); a missing
one is warned (`W-GW-OUTCOME`): that answer has nowhere to go. A named
outgoing flow that matches no outcome, other than the gateway's `default`
flow, is also warned (`W-GW-FLOW`).

---

## 5. Envelopes

### 5.1 Element envelope — `tEnvelope`

The element envelope declares: `toolAllow` (tools the agent MAY use),
`toolDeny` (tools the agent MUST NOT use), `constraint` (compliance/policy
rules), and the bounding attributes `confidenceThreshold` (0–1; below it the
agent MUST escalate rather than act), `maxSteps`, `timeBudget` (ISO 8601
duration), `retryPolicy`, `audited`, and `irreversible`. If
`irreversible="true"`, a conformant runtime MUST gate the action behind human
approval before any externally visible side effect. In the diagram, the gate
is a human-controlled element (`userTask` or `manualTask`) immediately
upstream of the irreversible element (§7.1).

### 5.2 Scope envelope — `tScopeEnvelope`

The lane and participant scopes use a **scope envelope**: identical to the
element envelope but WITHOUT `irreversible`. Irreversibility is a property of
a concrete action, never of a band of work or a whole participant. The XSD
enforces this — `irreversible` is not permitted on a scope envelope.

---

## 6. The inheritance model (normative)

This section defines precisely how a narrower scope's effective policy is
computed from the broader scopes that contain it. A conformant runtime MUST
compute effective policy exactly as specified here. Ambiguity in this
algorithm would make guardrails resolve differently across runtimes, which is
worse than no guardrail; therefore the algorithm is fully specified.

### 6.1 Scope chain

For any enhanced element E, the **scope chain** from broadest to narrowest is:

```
[ participant envelope? ] → [ lane envelope? (outer → inner) ]* → [ element envelope ]
```

The participant envelope is present only if E belongs to a whiteBox
participant carrying a `participantEnhancement` with an envelope. A lane
envelope is present for each lane, from outermost to innermost, that contains
E (directly by `flowNodeRef`, or by enclosing the `childLaneSet` of a lane
that does) and carries a `laneEnhancement` with an envelope. Absent scopes
are skipped.

### 6.2 Merge function

The effective policy is computed by folding the scope chain from broadest to
narrowest with the following per-field merge rules. In all cases the principle
is identical: **the result is the strictest of the combined values.**

| Field                  | Merge rule (broader ⊕ narrower)                                  |
|------------------------|------------------------------------------------------------------|
| `toolDeny`             | **Union.** Denials accumulate and are binding.                  |
| `constraint`           | **Union.** Constraints accumulate and are binding.              |
| `toolAllow`            | **Union, then subtract all `toolDeny`.** A narrower scope may add allowances, but any tool denied at ANY scope is removed. Denial always wins. |
| `confidenceThreshold`  | **Maximum.** Higher threshold = more cautious = stricter.        |
| `maxSteps`             | **Minimum.** Fewer steps = stricter.                            |
| `timeBudget`           | **Minimum** of the durations, compared in seconds (Y = 365 d, M = 30 d, W = 7 d). Shorter budget = stricter. |
| `audited`              | **Logical OR.** If any scope requires audit, the result is audited. |
| `irreversible`         | Element scope only (not inheritable; scope envelopes lack it).  |
| `retryPolicy`          | **Narrower wins** if present, else inherit broader. (Descriptor, not numerically comparable; the element is the most specific authority on its own retry behavior, but it cannot grant itself a denied tool to retry against.) |

### 6.3 The non-relaxation guarantee

It follows from §6.2 that for every field except `retryPolicy`, the effective
value at the element is at least as strict as the value at any broader scope.
Specifically:

- A tool denied at the lane or participant scope is denied at the element,
  regardless of any element-level `toolAllow`. **An element can never grant
  itself a tool its lane or participant forbids.**
- A compliance constraint declared at a broader scope always applies.
- A confidence floor set at a broader scope can only be raised, never lowered.
- An audit requirement set at a broader scope always holds.

A conformant document SHOULD NOT contain a contradiction (e.g. an element
`toolAllow` naming a tool its lane denies). A conformant validator MUST flag
such a contradiction as an error, because although the merge resolves it
safely (denial wins), its presence signals author confusion and a misleading
diagram.

### 6.4 Participant chain for whiteBox pools

If E belongs to a whiteBox participant with a participant envelope, that
envelope is the broadest scope in E's chain and merges by the same rules in
§6.2. For a blackBox participant there are no internal elements to inherit;
the participant envelope describes the participant as a whole.

### 6.5 Worked example

Lane envelope: `toolDeny=[email.send]`, `audited=true`,
`confidenceThreshold=0.6`.
Element envelope: `toolAllow=[crm.read, email.send]`,
`confidenceThreshold=0.8`, `irreversible=false`.

Effective policy at the element:
- `toolDeny` = `[email.send]` (from lane)
- `toolAllow` = `[crm.read, email.send]` minus `[email.send]` = `[crm.read]`
  — the element's attempt to allow `email.send` is overridden by the lane denial.
- `confidenceThreshold` = max(0.6, 0.8) = `0.8`
- `audited` = true OR (unset) = `true`
- `irreversible` = `false` (element scope)

---

## 7. Conformance

### 7.1 A conformant BPMNx *document*

- Is a valid BPMN 2.0 document.
- Attaches each scope marker only to its permitted host (§2).
- Attaches `enhancement` to a typed event only, never a plain event (§2.1).
- Has every BPMNx extension validate against the BPMNx 1.1 XSD.
- Has every `onFailRef` and `targetRef` resolve to a real element id that is
  reachable by sequence flow from the enhanced element (§4.3).
- Contains no inheritance contradiction at any scope — participant, lane or
  element (§6.3).
- Ensures any element with `irreversible="true"` is immediately preceded in
  the flow by a human-controlled element (`userTask` or `manualTask`) that
  gates it. A human element only *after* the irreversible one is a warning,
  not a gate: approval must come before the side effect.
- SHOULD route every declared outcome of an AI gateway (§4.4).

Diagnostic codes are defined by the reference implementation (Bench) and
mirrored by `tools/validate_bpmnx.py`; `tests/parity.mjs` keeps them equal.

### 7.2 A conformant BPMNx *runtime*

- MUST execute the underlying BPMN process per BPMN 2.0 semantics.
- MUST compute each enhanced element's effective policy per §6.
- MUST enforce `toolDeny` over `toolAllow` at every scope.
- MUST escalate (not act) when `confidenceThreshold` is not met.
- MUST gate `irreversible="true"` actions behind human approval.
- MUST run declared reviews before output is consumed, routing to `onFailRef`
  after `maxRetries`.
- MAY ignore `property` elements it does not recognize.

### 7.3 A conformant BPMN-only tool

- Ignores the `bpmnx` namespace and processes the file as BPMN 2.0. This
  requires no BPMNx awareness; it is BPMN 2.0's defined behavior for unknown
  extension content.

---

## 8. Relationship to BPMN 2.0 visuals

BPMNx adds no new diagram shapes to BPMN. How a BPMNx-aware renderer visually
distinguishes enhanced elements (for example, a modified border treatment, or
a tinted lane background for an enhanced lane) is a presentation concern, not
part of this notation standard, and is left to implementations. The standard
defines meaning and constraints, not pixels.

---

## 9. Versioning

This is BPMNx 1.1. The `version` attribute is fixed to `"1.1"` and the
namespace is `http://bpmnx.org/schema/1.1/bpmnx`. Future revisions increment
both. The `<property>` element lets implementations carry additional data
without waiting for a schema revision. Backward-incompatible changes to the
merge algorithm (§6) require a major version increment.

**Legacy 1.0 documents.** A conformant 1.1 tool MUST accept a document that
uses only the 1.0 namespace. It validates the markers against the 1.0 XSD,
applies the 1.1 rules, and reports `W-LEGACY-NS`. A document that mixes both
namespaces is an error (`E-NS-MIXED`). `tools/migrate_1_0_to_1_1.py` rewrites
a 1.0 document to 1.1.

---

## 10. Changes in 1.1

| Area | 1.0 | 1.1 |
|---|---|---|
| Namespace / `version` | `…/schema/1.0/bpmnx`, `"1.0"` | `…/schema/1.1/bpmnx`, `"1.1"`; 1.0 accepted as legacy (§9) |
| Determinism | implied "AI-operated" | explicit AI vs Program categories; Program elements are agent-operated tools (§3.3) |
| Enhanceable events | start/end typed; intermediate catch | adds typed `boundaryEvent`; `intermediateThrowEvent` explicitly excluded (§2.1) |
| `onFailRef` / `targetRef` | must resolve to an id | must also be reachable by drawn sequence flow (§4.3) |
| AI gateway outcomes | — | each declared outcome needs a named outgoing flow (§4.4) |
| Nested lanes | unspecified | every enclosing lane envelope is in the chain (§6.1) |
| `timeBudget` merge | minimum | minimum, with the duration comparison defined (§6.2) |
| Contradictions | lane ↔ element | participant, lane and element (§6.3, §7.1) |
| Irreversible gate | "followed by" a human element | immediately *preceded* by a human element (§5.1, §7.1) |
| Reference implementation | — | the Bench; Python tools are a parity-tested port |
