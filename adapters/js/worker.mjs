// Worker thread: loads one library module (lib_<name>.mjs) and runs its operations on the cases
// the main thread sends. Each operation's result is posted as soon as it is known, so the main
// thread can kill this worker on a hang or crash and resume with the next operation.
import { parentPort, workerData } from 'node:worker_threads';
import util from 'node:util';
import { fmtErr, Unsupported } from './common.mjs';

// Library console output goes to stderr (worker stdout is also piped to stderr by the main
// thread), truncated and capped so a chatty library cannot flood the log.
const LOG_MAX = Number(process.env.JS_ADAPTER_LIB_LOG_MAX ?? 20);
let nLog = 0;
for (const m of ['log', 'info', 'debug', 'warn', 'error', 'trace']) {
  console[m] = (...args) => {
    nLog++;
    if (nLog <= LOG_MAX) {
      let s = util.format(...args);
      if (s.length > 300) s = s.slice(0, 300) + '...';
      process.stderr.write(`[${workerData.lib}] console.${m}: ${s}\n`);
    } else if (nLog === LOG_MAX + 1) {
      process.stderr.write(`[${workerData.lib}] further library console output suppressed in this worker\n`);
    }
  };
}

const mod = await import(`./lib_${workerData.lib}.mjs`);
const OPS = mod.OPS;

// Fault injection for testing the isolation code only: JS_ADAPTER_TEST_FAULT=hang:<key>,
// crash:<key> or oom:<key>.
const [faultKind, faultKey] = (process.env.JS_ADAPTER_TEST_FAULT || ':').split(':');

function inject(key) {
  if (key !== faultKey) return;
  if (faultKind === 'hang') for (;;);
  if (faultKind === 'crash') process.exit(70);
  if (faultKind === 'oom') { const hog = []; for (;;) hog.push(new Array(1e6).fill(hog.length)); }
}

function check(key, v) {
  if (key.startsWith('area_')) {
    if (typeof v !== 'number' || !Number.isFinite(v)) throw new Error(`non-finite or non-numeric area: ${v}`);
  } else if (typeof v !== 'boolean') {
    throw new Error(`non-boolean result: ${util.inspect(v, { depth: 1 })}`);
  }
  return v;
}

function checkV2(path, v) {
  if (v === undefined || v === null) return null;
  if (path === 'relate') {
    if (typeof v !== 'string' || !/^[F012]{9}$/.test(v)) throw new Error(`not a DE-9IM matrix: ${util.inspect(v)}`);
  } else if (path.startsWith('predicates.') || path.startsWith('valid_')) {
    if (typeof v !== 'boolean') throw new Error(`non-boolean result: ${util.inspect(v, { depth: 1 })}`);
  } else if (v === null || typeof v !== 'object') {
    throw new Error(`not a geometry: ${util.inspect(v, { depth: 1 })}`);
  }
  return v;
}

const OPS_V2 = mod.OPS_V2 || {};

parentPort.on('message', ({ seq, kase, start, paths }) => {
  const n = paths ? paths.length : OPS.length;
  for (let k = start; k < n; k++) {
    const out = { seq, k };
    const t0 = performance.now();
    if (paths) {  // contract v2
      const path = paths[k];
      const fn = OPS_V2[path];
      try {
        inject(path);
        out.value = fn ? checkV2(path, fn(kase)) : null;
      } catch (e) {
        if (e instanceof Unsupported) out.value = 'unsupported';
        else out.error = fmtErr(e);
      }
    } else {  // contract v1
      const [key, fn] = OPS[k];
      try {
        inject(key);
        out.value = check(key, fn(kase));
      } catch (e) {
        out.error = fmtErr(e);
      }
    }
    out.ms = performance.now() - t0;
    parentPort.postMessage(out);
  }
});

parentPort.postMessage({ type: 'ready', lib: mod.LIB, keys: (OPS || []).map((o) => o[0]), note: mod.NOTE ?? null });
