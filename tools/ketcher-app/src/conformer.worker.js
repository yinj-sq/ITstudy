import { Molecule, ConformerGenerator, Resources } from 'openchemlib';
import resources from './ocl-resources.json';

const MAX_3D_ATOMS = 160;
Resources.register(resources);

function build3d(molfile, smiles) {
  let mol = null;
  if (molfile && /V2000|V3000/.test(molfile) && !/^\s*\$RXN/m.test(molfile)) {
    try {
      mol = Molecule.fromMolfile(molfile);
    } catch (e) {
      mol = null;
    }
  }
  if ((!mol || mol.getAllAtoms() === 0) && smiles && !/[>*]/.test(smiles)) {
    try {
      mol = Molecule.fromSmiles(smiles);
    } catch (e) {
      mol = null;
    }
  }
  if (!mol || mol.getAllAtoms() === 0) {
    throw new Error('当前内容不是可用于 3D 的分子结构');
  }
  if (mol.getAllAtoms() > MAX_3D_ATOMS) {
    throw new Error(`结构包含 ${mol.getAllAtoms()} 个原子，超出离线 3D 生成上限`);
  }
  const generator = new ConformerGenerator(20261116);
  const conformer = generator.getOneConformerAsMolecule(mol);
  if (!conformer) throw new Error('未能生成 3D 构象');
  return conformer.toMolfile();
}

self.onmessage = (event) => {
  const { id, molfile, smiles } = event.data || {};
  try {
    const result = build3d(molfile, smiles);
    self.postMessage({ id, ok: true, molfile: result });
  } catch (err) {
    self.postMessage({
      id,
      ok: false,
      error: (err && err.message) || String(err),
    });
  }
};
