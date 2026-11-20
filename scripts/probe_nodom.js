// Probe: can Turnstile token be produced WITHOUT a browser?
// Loads the real api.js (already downloaded) in bare Node and in jsdom.
const fs = require('fs');
const path = 'api.js';

function probeA() {
  console.log('=== PROBE A: bare Node (no DOM) ===');
  const src = fs.readFileSync(path, 'utf8');
  const sandbox = {}; // globalThis
  try {
    // api.js expects a browser global scope; give it the real one to see how far it gets
    (0, eval)(src);
    console.log('  eval succeeded');
    console.log('  typeof window.turnstile =', typeof (globalThis.window && globalThis.window.turnstile));
  } catch (e) {
    console.log('  eval threw:', e.constructor.name + ': ' + String(e.message).slice(0, 160));
    return { survived: false, error: e.message.slice(0, 160) };
  }
  return { survived: true };
}

function probeB() {
  console.log('\n=== PROBE B: jsdom (DOM but no real browser) ===');
  let JSDOM;
  try {
    ({ JSDOM } = require('jsdom'));
  } catch (e) {
    console.log('  jsdom not installed — cannot probe. (this is itself a finding:');
    console.log('   the skill must not depend on jsdom)');
    return { available: false };
  }
  const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', {
    url: 'https://demo.turnstile.workers.dev/',
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
  });
  const src = fs.readFileSync(path, 'utf8');
  try {
    dom.window.eval(src);
    console.log('  api.js loaded into jsdom');
    console.log('  typeof window.turnstile =', typeof dom.window.turnstile);
    if (dom.window.turnstile) {
      console.log('  turnstile keys:', Object.keys(dom.window.turnstile).join(','));
    }
    return { available: true, loaded: true, hasTurnstile: typeof dom.window.turnstile };
  } catch (e) {
    console.log('  jsdom eval threw:', String(e.message).slice(0, 200));
    return { available: true, loaded: false, error: e.message.slice(0, 200) };
  }
}

const a = probeA();
const b = probeB();

console.log('\n=== VERDICT ===');
if (!a.survived && (!b.available || !b.loaded)) {
  console.log('CONFIRMED: api.js cannot run without a DOM/browser.');
  console.log('  -> token generation REQUIRES a real JS engine with DOM.');
  console.log('  -> no-browser path can only reach classification + sitekey extraction.');
} else if (a.survived) {
  console.log('api.js survived bare Node — token path may be reachable without DOM.');
} else {
  console.log('api.js loads under jsdom — a DOM shim is viable, but still no browser.');
}