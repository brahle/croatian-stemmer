import { copyFile, mkdir, readFile, writeFile } from 'node:fs/promises';
const statics = new URL('../src/croatian_stemmer/labeling/web/static/', import.meta.url);
const destination = new URL('vendor/', statics);
await mkdir(destination, { recursive: true });
await copyFile(new URL('../node_modules/keycloak-js/lib/keycloak.js', import.meta.url), new URL('keycloak.js', destination));
await copyFile(new URL('../node_modules/keycloak-js/LICENSE.txt', import.meta.url), new URL('LICENSE.txt', destination));
// The release version from pyproject.toml; the UI sends it with every answer as client_version.
const pyproject = await readFile(new URL('../pyproject.toml', import.meta.url), 'utf8');
const version = pyproject.match(/^version = "([0-9A-Za-z._-]{1,32})"$/m)?.[1];
if (!version) throw new Error('pyproject.toml has no usable [project].version');
await writeFile(new URL('version.js', statics), `export const version = ${JSON.stringify(version)};\n`);
