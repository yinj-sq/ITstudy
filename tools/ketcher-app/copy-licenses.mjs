import fs from 'node:fs';
import path from 'node:path';

const dest = path.resolve('../../static/chem-lab/ketcher/LICENSES');
fs.mkdirSync(dest, { recursive: true });
const files = {
  'KETCHER-APACHE-2.0.txt': 'node_modules/indigo-ketcher/LICENSE',
  'OPENCHEMLIB-BSD-3.txt': 'node_modules/openchemlib/LICENSE',
  'RAPHAEL-MIT.txt': 'node_modules/raphael/license.txt',
  'REACT-MIT.txt': 'node_modules/react/LICENSE',
};
for (const [name, src] of Object.entries(files)) {
  fs.copyFileSync(src, path.join(dest, name));
}
console.log(`licenses copied: ${Object.keys(files).length}`);
