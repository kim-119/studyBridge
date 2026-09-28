import { readFile, stat } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { transform } from 'esbuild';

const RESOLVABLE_EXTENSIONS = ['.js', '.jsx', '.mjs', '/index.js', '/index.jsx'];
const STYLE_EXTENSION_PATTERN = /\.(css|scss|svg|png|jpe?g|gif|webp)$/i;
const TRANSFORMED_EXTENSION_PATTERN = /\.(jsx|js)$/i;
const STUB_URL_PREFIX = 'stub-asset:';

const IMPORT_META_ENV = JSON.stringify({
  DEV: false,
  PROD: true,
  MODE: 'test',
  VITE_API_BASE_URL: 'https://studybridge.test',
  VITE_FASTAPI_BASE_URL: 'https://studybridge.test',
});

let moduleOverrides = {};

export function initialize(data) {
  moduleOverrides = data?.moduleOverrides || {};
}

async function isFile(path) {
  try {
    return (await stat(path)).isFile();
  } catch {
    return false;
  }
}

function isRelativeOrAbsolute(specifier) {
  return specifier.startsWith('./') || specifier.startsWith('../') || specifier.startsWith('file:');
}

async function resolveWithExtensions(specifier, parentURL) {
  const candidateURL = new URL(specifier, parentURL);
  const basePath = fileURLToPath(candidateURL);

  if (await isFile(basePath)) return pathToFileURL(basePath).href;

  for (const extension of RESOLVABLE_EXTENSIONS) {
    if (await isFile(basePath + extension)) return pathToFileURL(basePath + extension).href;
  }

  return null;
}

export async function resolve(specifier, context, nextResolve) {
  if (STYLE_EXTENSION_PATTERN.test(specifier)) {
    return { url: `${STUB_URL_PREFIX}${specifier}`, shortCircuit: true };
  }

  if (context.parentURL && isRelativeOrAbsolute(specifier)) {
    const resolvedURL = await resolveWithExtensions(specifier, context.parentURL);

    if (resolvedURL) {
      const override = moduleOverrides[fileURLToPath(resolvedURL)];
      if (override) return { url: pathToFileURL(override).href, shortCircuit: true };
      return { url: resolvedURL, shortCircuit: true };
    }
  }

  return nextResolve(specifier, context);
}

function isProjectSource(url) {
  return url.startsWith('file:') && !url.includes('/node_modules/') && TRANSFORMED_EXTENSION_PATTERN.test(url);
}

export async function load(url, context, nextLoad) {
  if (url.startsWith(STUB_URL_PREFIX)) {
    return { format: 'module', source: 'export default "";', shortCircuit: true };
  }

  if (!isProjectSource(url)) return nextLoad(url, context);

  const source = await readFile(fileURLToPath(url), 'utf8');
  const result = await transform(source, {
    loader: 'jsx',
    format: 'esm',
    jsx: 'automatic',
    sourcefile: fileURLToPath(url),
    define: { 'import.meta.env': IMPORT_META_ENV },
  });

  return { format: 'module', source: result.code, shortCircuit: true };
}
