import { copyFile, mkdir } from 'node:fs/promises';
const destination = new URL('../src/croatian_stemmer/labeling/web/static/vendor/', import.meta.url);
await mkdir(destination, { recursive: true });
await copyFile(new URL('../node_modules/keycloak-js/lib/keycloak.js', import.meta.url), new URL('keycloak.js', destination));
await copyFile(new URL('../node_modules/keycloak-js/LICENSE.txt', import.meta.url), new URL('LICENSE.txt', destination));
