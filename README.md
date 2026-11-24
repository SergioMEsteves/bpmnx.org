# BPMNx

**BPMNx 1.1** is an open extension to the OMG BPMN 2.0 standard for modeling
agentic workflows. It declares, inside BPMN's own `<bpmn:extensionElements>`,
which parts of a process are operated by agents, whether each one runs on
model judgment (**AI**) or fixed logic (**Program**), and the guardrails that
bound them.

A BPMNx file **is** a BPMN 2.0 file. It opens in bpmn.io, Camunda Modeler or
any BPMN 2.0 tool; tools that don't know BPMNx ignore the extension.

```xml
<bpmn:serviceTask id="Task_Classify" name="Classify &amp; Score">
  <bpmn:extensionElements>
    <bpmnx:enhancement version="1.1" determinism="nondeterministic">
      <bpmnx:agent role="qualifier"/>
      <bpmnx:envelope confidenceThreshold="0.7" audited="true">
        <bpmnx:toolAllow ref="crm.read"/>
        <bpmnx:toolDeny ref="email.send"/>
      </bpmnx:envelope>
    </bpmnx:enhancement>
  </bpmn:extensionElements>
</bpmn:serviceTask>
```

## What's here

| Path | What |
|---|---|
| [`spec/SPECIFICATION.md`](spec/SPECIFICATION.md) | The specification (normative). Changes from 1.0 are in §10. |
| [`bench/index.html`](bench/index.html) | **BPMNx Bench**: open in a browser, load a `.bpmn`, see the diagram, conformance report, resolved policy per element, and step tokens through it. It is the reference implementation. |
| [`schema/bpmnx-1.1.xsd`](schema/bpmnx-1.1.xsd) | XSD for the extension vocabulary (`bpmnx-1.0.xsd` kept for legacy files). |
| [`tools/`](tools) | Python CLI: validator, policy resolver, 1.0 → 1.1 migrator, BPMNDI layout generator. |
| [`examples/`](examples) | Element scope, lane inheritance (one deliberately failing), black-box participant. |
| [`tests/`](tests) | Parity test (Bench engine vs Python port) and fixture tests. |

## Use

```bash
pip install -r requirements.txt

python tools/validate_bpmnx.py examples/*.bpmn          # conformance (§7)
python tools/resolve_policy.py examples/02b-lane-inheritance-clean.bpmn   # effective policy (§6)
python tools/migrate_1_0_to_1_1.py --in-place old.bpmn  # 1.0 -> 1.1
python tools/add_bpmndi.py --in-place file.bpmn         # generate a diagram layout
```

Or open `bench/index.html` and drag a file in.

## Develop

```bash
pip install -r requirements.txt pytest
(cd tests && npm ci)
pytest -q tests          # fixtures + expected diagnostics
node tests/parity.mjs    # Bench and Python must agree on every file
```

The Bench is authoritative. A rule change goes into the Bench's engine region
(between `@engine:begin` and `@engine:end`) first, then into
`tools/bpmnx_core.py`; CI fails until both agree.

## License

Apache-2.0
