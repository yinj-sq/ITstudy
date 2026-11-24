import './require-shim.js';
import './i18n.js';
import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Editor } from 'ketcher-react';
import { StandaloneStructServiceProvider } from 'ketcher-standalone';
import { Molecule } from 'openchemlib';
import 'ketcher-react/dist/index.css';
import './app.css';

const STATIC_BASE = '/static/chem-lab/ketcher/';
const structServiceProvider = new StandaloneStructServiceProvider();

let ketcher = null;
let readySent = false;
let syncTimer = null;
let busy = false;
let dirty = false;
let suppressChange = false;

let conformerWorker = null;
let conformerSeq = 0;
const conformerPending = new Map();

function notify(type, payload = {}) {
  try {
    window.parent.postMessage({ type, ...payload }, window.location.origin);
  } catch (e) {
    /* 父页面不可用时静默 */
  }
}

function ensureConformerWorker() {
  if (conformerWorker) return conformerWorker;
  conformerWorker = new Worker(
    new URL('./conformer.worker.js', import.meta.url),
    { type: 'module' },
  );
  conformerWorker.onmessage = (event) => {
    const data = event.data || {};
    const pending = conformerPending.get(data.id);
    if (!pending) return;
    conformerPending.delete(data.id);
    clearTimeout(pending.timer);
    if (data.ok) pending.resolve(data.molfile);
    else pending.reject(new Error(data.error || '3D 构象生成失败'));
  };
  conformerWorker.onerror = (event) => {
    const message = (event && event.message) || '本地 3D 计算线程启动失败';
    conformerPending.forEach((pending) => {
      clearTimeout(pending.timer);
      pending.reject(new Error(message));
    });
    conformerPending.clear();
    conformerWorker = null;
  };
  return conformerWorker;
}

function generate3d(molfile, smiles) {
  return new Promise((resolve, reject) => {
    const id = ++conformerSeq;
    const timer = setTimeout(() => {
      conformerPending.delete(id);
      reject(new Error('3D 构象生成超时'));
    }, 20000);
    conformerPending.set(id, { resolve, reject, timer });
    ensureConformerWorker().postMessage({ id, molfile, smiles });
  });
}

function moleculeInfo(molfile, smiles) {
  try {
    let mol = null;
    if (molfile) {
      try {
        mol = Molecule.fromMolfile(molfile);
      } catch (e) {
        mol = null;
      }
    }
    if ((!mol || mol.getAllAtoms() === 0) && smiles) {
      mol = Molecule.fromSmiles(smiles);
    }
    if (!mol || mol.getAllAtoms() === 0) return null;
    const formula = mol.getMolecularFormula();
    return {
      formula: formula.formula,
      weight: Math.round(formula.relativeWeight * 100) / 100,
      atoms: mol.getAllAtoms(),
    };
  } catch (e) {
    return null;
  }
}

async function syncStructure() {
  if (!ketcher) return;
  if (busy) {
    dirty = true;
    return;
  }
  busy = true;
  let molfile = '';
  let smiles = '';
  try {
    molfile = await ketcher.getMolfile();
    try {
      smiles = await ketcher.getSmiles();
    } catch (e) {
      smiles = '';
    }
    const info = moleculeInfo(molfile, smiles);
    notify('chem-sketch-change', { molfile, smiles, info });
    if (!info || !info.atoms) {
      notify('chem-sketch-3d-empty');
      return;
    }
    try {
      const mol3d = await generate3d(molfile, smiles);
      notify('chem-sketch-3d', { molfile: mol3d, smiles });
    } catch (err) {
      notify('chem-sketch-3d-error', { message: (err && err.message) || String(err) });
    }
  } catch (err) {
    notify('chem-sketch-3d-error', { message: (err && err.message) || String(err) });
  } finally {
    busy = false;
    if (dirty) {
      dirty = false;
      scheduleSync(500);
    }
  }
}

function scheduleSync(delay = 700) {
  if (suppressChange) return;
  clearTimeout(syncTimer);
  syncTimer = setTimeout(syncStructure, delay);
}

async function loadStructure(data) {
  if (!ketcher) return;
  suppressChange = true;
  clearTimeout(syncTimer);
  try {
    const text = String(data || '').trim();
    if (!text) {
      await ketcher.setMolecule('');
      return;
    }
    // Ketcher/Indigo 的 SMILES 自动识别对芳香小写写法（如 c1ccccc1）
    // 会按单键环解析；先用 OpenChemLib 规范化为 2D molfile 再载入。
    if (!/V2000|V3000|M {2}END/.test(text)) {
      try {
        const mol = Molecule.fromSmiles(text);
        if (mol && mol.getAllAtoms() > 0) {
          await ketcher.setMolecule(mol.toMolfile());
          return;
        }
      } catch (e) {
        /* 可能是反应式 SMILES，交给 Ketcher 处理 */
      }
    }
    await ketcher.setMolecule(text);
  } catch (err) {
    notify('chem-sketch-3d-error', { message: '载入结构失败：' + ((err && err.message) || err) });
  } finally {
    setTimeout(() => {
      suppressChange = false;
      scheduleSync(120);
    }, 120);
  }
}

function App() {
  const [ready, setReady] = useState(false);
  const pending = useRef([]);

  useEffect(() => {
    const onMessage = (event) => {
      if (event.origin !== window.location.origin) return;
      const msg = event.data || {};
      if (msg.type === 'chem-sketch-load') {
        if (ketcher) loadStructure(msg.data);
        else pending.current.push(msg);
      } else if (msg.type === 'chem-sketch-clear') {
        if (ketcher) loadStructure('');
      } else if (msg.type === 'chem-sketch-ping') {
        if (readySent) notify('chem-sketch-ready');
      } else if (msg.type === 'chem-sketch-sync') {
        scheduleSync(0);
      }
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  useEffect(() => {
    if (!ready) return;
    pending.current.splice(0).forEach((msg) => loadStructure(msg.data));
  }, [ready]);

  const handleInit = (api) => {
    ketcher = api;
    window.ketcher = api;
    try {
      api.changeEvent.add(() => scheduleSync());
    } catch (e) {
      /* 旧版本无 changeEvent 时依赖父子页面手动同步 */
    }
    setReady(true);
    if (!readySent) {
      readySent = true;
      notify('chem-sketch-ready');
    }
  };

  return (
    <Editor
      staticResourcesUrl={STATIC_BASE}
      structServiceProvider={structServiceProvider}
      onInit={handleInit}
      disableMacromoleculesEditor
      errorHandler={(message) => notify('chem-sketch-error', { message })}
    />
  );
}

createRoot(document.getElementById('root')).render(<App />);
