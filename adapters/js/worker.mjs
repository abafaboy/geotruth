// Worker thread: loads one library module (lib_<name>.mjs) and runs its operations on the cases
// the main thread sends. Each operation's result is posted as soon as it is known, so the main
// thread can kill this worker on a hang or crash and resume with the next operation.
import { parentPort, workerData } from 'node:worker_threads';
import util from 'node:util';
import { fmtErr } from './common.mjs';

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

parentPort.on('message', ({ seq, kase, start }) => {
  for (let k = start; k < OPS.length; k++) {
    const [key, fn] = OPS[k];
    const out = { seq, k };
    try {
      inject(key);
      out.value = check(key, fn(kase));
    } catch (e) {
      out.error = fmtErr(e);
    }
    parentPort.postMessage(out);
  }
});

parentPort.postMessage({ type: 'ready', lib: mod.LIB, keys: OPS.map((o) => o[0]), note: mod.NOTE ?? null });
