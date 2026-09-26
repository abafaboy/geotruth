#!/usr/bin/env node
// Adapter driver for the JavaScript libraries: adapter contract v2 (docs/DESIGN.md §4.1,
// schemas/result.v2.schema.json) for typed lines, and the legacy FORMAT-v1 contract
// (../../harness/FORMAT-v1.md) for legacy lines.
//
//   node adapter.mjs <turf|polygon_clipping|polyclip_ts|martinez|jsts> [--v2] [--timing] CASES.jsonl|- > RESULTS.jsonl
//   node adapter.mjs <lib> --version
//
// A line is answered with contract v2 when an operand is a typed geometry (an object) or
// "ops" is present (--v2: every line); lib_<name>.mjs provides OPS_V2 (field path ->
// function) and OPS (the v1 fields).
//
// The library runs in a worker thread (worker.mjs + lib_<name>.mjs). Every operation's result
// is sent back as soon as it is known. If one operation gives no result within
// JS_ADAPTER_TIMEOUT (or GEOTRUTH_OP_TIMEOUT) seconds (default 10) the worker is terminated,
// that field is null with a timeout error (v1: "timeout: ..." and errors.timeout; v2:
// {"kind": "timeout"}), and a fresh worker carries on with the next operation. A worker that
// dies (out of memory under the JS_ADAPTER_MEM_MB heap cap, default 2048) is handled the same
// way with a crash error. Output numbers are written by jsonOut (common.mjs): shortest
// round-trip, -0.0 kept, NaN / Infinity as Python's json module writes them.
import fs from 'node:fs';
import readline from 'node:readline';
import { Worker } from 'node:worker_threads';
import { FIELDS, fmtErr, isV2, jsonOut, requestedPaths, PREDICATES_V2, OVERLAYS_V2 } from './common.mjs';

const LIBS = ['turf', 'polygon_clipping', 'polyclip_ts', 'martinez', 'jsts'];
const argv = process.argv.slice(2);
const libName = argv[0];
const flags = new Set(argv.slice(1).filter((a) => a.startsWith('--')));
const files = argv.slice(1).filter((a) => !a.startsWith('--') || a === '-');
const casesPath = files[0];
if (!LIBS.includes(libName) || (!casesPath && !flags.has('--version'))) {
  process.stderr.write(`usage: node adapter.mjs <${LIBS.join('|')}> [--v2] [--timing] CASES.jsonl|- > RESULTS.jsonl\n`);
  process.exit(2);
}
const FORCE_V2 = flags.has('--v2');
const TIMING = flags.has('--timing');
const TIMEOUT_S = Number(process.env.JS_ADAPTER_TIMEOUT || process.env.GEOTRUTH_OP_TIMEOUT || 10);
const MEM_MB = Number(process.env.JS_ADAPTER_MEM_MB ?? 2048);
const WORKER_URL = new URL('./worker.mjs', import.meta.url);

class Host {
  constructor() { this.w = null; this.pending = null; this.seq = 0; this.info = null; }

  async ensure() {
    if (this.w) return;
    const w = new Worker(WORKER_URL, {
      workerData: { lib: libName },
      stdout: true, // never let library output reach our stdout
      resourceLimits: MEM_MB > 0 ? { maxOldGenerationSizeMb: MEM_MB } : undefined,
    });
    w.stdout.pipe(process.stderr, { end: false });
    this.w = w;
    const info = await new Promise((resolve, reject) => {
      const done = (f, x) => { w.off('message', onMsg); w.off('error', onErr); w.off('exit', onExit); f(x); };
      const onMsg = (m) => { if (m && m.type === 'ready') done(resolve, m); };
      const onErr = (e) => done(reject, e);
      const onExit = (c) => done(reject, new Error(`worker exited with code ${c} while starting`));
      w.on('message', onMsg); w.on('error', onErr); w.on('exit', onExit);
    });
    if (!this.info) {
      this.info = info;
      if (info.note) process.stderr.write(`${info.lib}: ${info.note}\n`);
    }
    w.on('message', (m) => { if (this.w === w) this.pending?.onMessage(m); });
    w.on('error', (e) => { if (this.w === w) { this.w = null; w.terminate(); this.pending?.onDeath(`crash: ${fmtErr(e)}`); } });
    w.on('exit', (c) => { if (this.w === w) { this.w = null; this.pending?.onDeath(`crash: worker exited with code ${c}`); } });
  }

  kill() {
    const w = this.w;
    this.w = null;
    if (w) w.terminate();
  }

  // Runs operations start.. of one case; resolves with {done:true} or {k, reason, why}.
  runFrom(kase, start, nOps, onResult, paths) {
    return new Promise((resolve) => {
      const seq = ++this.seq;
      let expect = start, timer = null;
      const finish = (outcome) => { clearTimeout(timer); this.pending = null; resolve(outcome); };
      const arm = () => {
        clearTimeout(timer);
        timer = setTimeout(() => finish({ k: expect, reason: 'timeout' }), TIMEOUT_S * 1000);
      };
      this.pending = {
        onMessage: (m) => {
          if (m.seq !== seq) return;
          onResult(m);
          expect = m.k + 1;
          if (expect >= nOps) finish({ done: true }); else arm();
        },
        onDeath: (why) => finish({ k: expect, reason: 'crash', why }),
      };
      arm();
      this.w.postMessage({ seq, kase, start, paths });
    });
  }
}

function blankRecord(id, lib) {
  const rec = { id, lib };
  for (const f of FIELDS) rec[f] = null;
  rec.errors = {};
  return rec;
}

async function write(s) {
  if (!process.stdout.write(s)) await new Promise((r) => process.stdout.once('drain', r));
}

// The v2 record of a case (only the requested groups; errors keyed by field path).
function renderV2(id, lib, paths, res) {
  const by = new Map(paths.map((p, i) => [p, res[i]]));
  const val = (p) => (by.get(p) && 'value' in by.get(p) ? by.get(p).value : null);
  const parts = [`"id": ${jsonOut(id)}`, `"lib": ${jsonOut(lib)}`];
  if (by.has('relate')) parts.push(`"relate": ${jsonOut(val('relate'))}`);
  if (by.has('predicates.intersects')) {
    parts.push(`"predicates": {${PREDICATES_V2.map((p) => `"${p}": ${jsonOut(val(`predicates.${p}`))}`).join(', ')}}`);
  }
  if (by.has('valid_a')) parts.push(`"valid_a": ${jsonOut(val('valid_a'))}`, `"valid_b": ${jsonOut(val('valid_b'))}`);
  if (by.has('overlay.intersection')) {
    parts.push(`"overlay": {${OVERLAYS_V2.map((o) => `"${o}": ${jsonOut(val(`overlay.${o}`))}`).join(', ')}}`);
  }
  if (by.has('echo') && val('echo') !== null) parts.push(`"echo": ${jsonOut(val('echo'))}`);
  const errs = paths.filter((p) => by.get(p) && 'error' in by.get(p)).map((p) => `"${p}": ${jsonOut(by.get(p).error)}`);
  parts.push(`"errors": {${errs.join(', ')}}`);
  if (TIMING) {
    const t = paths.filter((p) => by.get(p) && typeof by.get(p).ms === 'number').map((p) => `"${p}": ${by.get(p).ms.toFixed(3)}`);
    parts.push(`"elapsed_ms": {${t.join(', ')}}`);
  }
  return `{${parts.join(', ')}}`;
}

async function answerV2(host, lib, kase) {
  const id = kase.id ?? null;
  let paths;
  try {
    if (!('a' in kase) || !('b' in kase)) throw new TypeError('missing "a" or "b"');
    paths = requestedPaths(kase);
  } catch (e) {
    return `{"id": ${jsonOut(id)}, "lib": ${jsonOut(lib)}, "errors": {"*": ${jsonOut(`input parse error: ${fmtErr(e)}`)}}}`;
  }
  const res = new Array(paths.length).fill(null);
  let start = 0;
  while (start < paths.length) {
    await host.ensure();
    const outcome = await host.runFrom(kase, start, paths.length, (m) => {
      res[m.k] = 'error' in m ? { error: m.error, ms: m.ms } : { value: m.value, ms: m.ms };
    }, paths);
    if (outcome.done) break;
    if (outcome.reason === 'timeout') {
      host.kill();
      res[outcome.k] = { error: { kind: 'timeout', message: `no result within ${TIMEOUT_S} s (worker terminated)` } };
    } else {
      res[outcome.k] = { error: { kind: 'crash', message: String(outcome.why).replace(/^crash: /, '') } };
    }
    start = outcome.k + 1;
  }
  return renderV2(id, lib, paths, res.map((r) => r ?? { value: null }));
}

async function main() {
  const host = new Host();
  try {
    await host.ensure();
  } catch (e) {
    process.stderr.write(`adapter: cannot start the ${libName} worker: ${fmtErr(e)}\n`);
    process.exit(2);
  }
  const { lib, keys } = host.info;
  if (flags.has('--version')) {
    await write(lib + '\n');
    host.kill();
    return;
  }
  const input = casesPath === '-' ? process.stdin : fs.createReadStream(casesPath);
  const rl = readline.createInterface({ input, crlfDelay: Infinity });
  for await (const line of rl) {
    if (!line.trim()) continue;
    let kase;
    try {
      kase = JSON.parse(line);
      if (kase === null || typeof kase !== 'object') throw new TypeError('case is not an object');
    } catch (e) {
      const rec = blankRecord(null, lib);
      rec.errors.parse = fmtErr(e);
      await write(JSON.stringify(rec) + '\n');
      continue;
    }
    if (FORCE_V2 || isV2(kase)) {
      await write((await answerV2(host, lib, kase)) + '\n');
      continue;
    }
    const rec = blankRecord(kase.id ?? null, lib);
    const timedOut = [];
    let start = 0;
    while (start < keys.length) {
      try {
        await host.ensure();
      } catch (e) {
        process.stderr.write(`adapter: cannot restart the ${libName} worker: ${fmtErr(e)}\n`);
        process.exit(2);
      }
      const outcome = await host.runFrom(kase, start, keys.length, (m) => {
        const key = keys[m.k];
        if ('error' in m) rec.errors[key] = m.error;
        else rec[key] = m.value;
      });
      if (outcome.done) break;
      const key = keys[outcome.k];
      if (outcome.reason === 'timeout') {
        host.kill();
        rec.errors[key] = `timeout: no result within ${TIMEOUT_S} s (worker terminated)`;
        timedOut.push(key);
      } else {
        rec.errors[key] = outcome.why;
      }
      start = outcome.k + 1;
    }
    if (timedOut.length) rec.errors.timeout = timedOut;
    await write(JSON.stringify(rec) + '\n');
  }
  host.kill();
}

main().catch((e) => {
  process.stderr.write(`adapter: fatal: ${e && e.stack ? e.stack : e}\n`);
  process.exit(1);
});
