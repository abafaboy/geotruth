#!/usr/bin/env node
// Adapter driver for the JavaScript libraries (contract: ../../FORMAT.md).
//
//   node adapter.mjs <turf|polygon_clipping|polyclip_ts|martinez> CASES.jsonl > RESULTS.jsonl
//
// The library runs in a worker thread (worker.mjs + lib_<name>.mjs). Every operation's result
// is sent back as soon as it is known. If one operation gives no result within
// JS_ADAPTER_TIMEOUT seconds (default 10) the worker is terminated, that field is null with a
// "timeout: ..." message (and its key is listed in errors.timeout), and a fresh worker carries on
// with the next operation. A worker that dies (out of memory under the JS_ADAPTER_MEM_MB heap
// cap, default 2048) is handled the same way with a "crash: ..." message.
import fs from 'node:fs';
import readline from 'node:readline';
import { Worker } from 'node:worker_threads';
import { FIELDS, fmtErr } from './common.mjs';

const LIBS = ['turf', 'polygon_clipping', 'polyclip_ts', 'martinez'];
const [libName, casesPath] = process.argv.slice(2);
if (!LIBS.includes(libName) || !casesPath) {
  process.stderr.write(`usage: node adapter.mjs <${LIBS.join('|')}> CASES.jsonl > RESULTS.jsonl\n`);
  process.exit(2);
}
const TIMEOUT_S = Number(process.env.JS_ADAPTER_TIMEOUT ?? 10);
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
  runFrom(kase, start, nOps, onResult) {
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
      this.w.postMessage({ seq, kase, start });
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

async function main() {
  const host = new Host();
  try {
    await host.ensure();
  } catch (e) {
    process.stderr.write(`adapter: cannot start the ${libName} worker: ${fmtErr(e)}\n`);
    process.exit(2);
  }
  const { lib, keys } = host.info;
  const rl = readline.createInterface({ input: fs.createReadStream(casesPath), crlfDelay: Infinity });
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
