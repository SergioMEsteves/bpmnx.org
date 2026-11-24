// Parity test: the BPMNx Bench (bench/index.html) is the authoritative engine.
// This script extracts the Bench's engine region (between @engine:begin and
// @engine:end), runs it in Node over every .bpmn file under examples/ and
// tests/fixtures/, and compares diagnostics + resolved policies against the
// Python port (tools/bpmnx_core.py). Any difference fails the run.
//
// Usage: node tests/parity.mjs            (from repo root or tests/)
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join, dirname, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { DOMParser } from '@xmldom/xmldom';

const here = dirname(fileURLToPath(import.meta.url));
const root = dirname(here);
const html = readFileSync(join(root, 'bench', 'index.html'), 'utf8');
const m = /\/\* @engine:begin[\s\S]*?\/\* @engine:end \*\//.exec(html);
if (!m) { console.error('engine markers not found in bench/index.html'); process.exit(2); }

// xmldom has no querySelector; the engine uses only standard DOM Level 2 calls.
const engine = new Function('DOMParser', 'document', 'window',
  m[0] + '\nreturn {parseModel, validate, effectivePolicy};')(DOMParser, {}, {});

function jsDump(xml) {
  const model = engine.parseModel(xml);
  if (!model.ok) return { ok: false };
  const diags = engine.validate(model)
    .filter(d => d.severity !== 'ok')
    .map(d => [d.severity, d.code, d.ref ?? null]).sort();
  const policies = {};
  for (const n of model.nodesById.values()) {
    if (!n.enh) continue;
    const p = engine.effectivePolicy(model, n);
    policies[n.id] = {
      chain: p.chain.map(c => c.scope),
      toolAllow: p.toolAllow.map(t => t.ref).sort(),
      toolDeny: p.toolDeny.map(t => t.ref).sort(),
      overridden: p.overridden.map(o => o.ref).sort(),
      constraints: p.constraints.map(c => c.text),
      confidenceThreshold: p.confidenceThreshold.val,
      maxSteps: p.maxSteps.val,
      timeBudget: p.timeBudget.val,
      retryPolicy: p.retryPolicy.val,
      audited: p.audited.val,
      irreversible: p.irreversible.val,
    };
  }
  return { ok: true, version: model.bpmnxVersion, diags, policies };
}

function files(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true }).flatMap(d =>
    d.isDirectory() ? files(join(dir, d.name)) : d.name.endsWith('.bpmn') ? [join(dir, d.name)] : []);
}
const all = [...files(join(root, 'examples')), ...files(join(here, 'fixtures'))];

const py = process.env.PYTHON || (existsSync(join(root, '.venv', 'Scripts', 'python.exe'))
  ? join(root, '.venv', 'Scripts', 'python.exe')
  : existsSync(join(root, '.venv', 'bin', 'python')) ? join(root, '.venv', 'bin', 'python') : 'python3');
const pyOut = JSON.parse(execFileSync(py, [join(here, 'dump_python.py'), ...all], { encoding: 'utf8' }));

let fail = 0;
for (const f of all) {
  const a = JSON.stringify(jsDump(readFileSync(f, 'utf8')));
  const b = JSON.stringify(pyOut[f]);
  const rel = relative(root, f);
  if (a === b) console.log(`  ✓ ${rel}`);
  else { fail++; console.log(`  ✗ ${rel}\n      bench : ${a}\n      python: ${b}`); }
}
console.log(fail ? `\nPARITY FAILED: ${fail}/${all.length}` : `\nPARITY OK: ${all.length} file(s)`);
process.exit(fail ? 1 : 0);
