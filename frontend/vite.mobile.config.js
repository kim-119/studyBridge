import { readdirSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const DEFAULT_API_BASE_URL = 'https://studybridge.co.kr';

function resolveApiBaseUrl() {
  const raw = process.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL;
  const normalized = raw.replace(/\/+$/, '');

  if (!normalized.startsWith('https://')) {
    throw new Error(
      `Mobile build needs an absolute https API base URL but received "${raw}". ` +
        'The Android WebView origin is https://localhost, so a relative path never reaches the server.'
    );
  }

  return normalized;
}

function useMobileEntry() {
  return {
    name: 'studybridge-mobile-entry',
    transformIndexHtml: {
      order: 'pre',
      handler(html) {
        const rewritten = html.replace('/src/main.jsx', '/src/mobile/main.jsx');

        if (rewritten === html) {
          throw new Error(
            'frontend/index.html no longer points at /src/main.jsx, so the mobile entry could not be swapped in.'
          );
        }

        return rewritten;
      },
    },
  };
}

const PDFJS_ASSET_DIRECTORIES = ['cmaps', 'standard_fonts'];

function emitPdfjsAssets() {
  const require = createRequire(import.meta.url);
  const pdfjsRoot = dirname(require.resolve('pdfjs-dist/package.json'));

  return {
    name: 'studybridge-pdfjs-assets',
    apply: 'build',
    generateBundle() {
      PDFJS_ASSET_DIRECTORIES.forEach((directory) => {
        const sourceDirectory = join(pdfjsRoot, directory);

        readdirSync(sourceDirectory).forEach((fileName) => {
          this.emitFile({
            type: 'asset',
            fileName: `pdfjs/${directory}/${fileName}`,
            source: readFileSync(join(sourceDirectory, fileName)),
          });
        });
      });
    },
  };
}

const apiBaseUrl = resolveApiBaseUrl();

export default defineConfig({
  plugins: [react(), useMobileEntry(), emitPdfjsAssets()],
  base: './',
  define: {
    global: 'window',
    'import.meta.env.VITE_API_BASE_URL': JSON.stringify(apiBaseUrl),
    'import.meta.env.VITE_FASTAPI_BASE_URL': JSON.stringify(apiBaseUrl),
  },
  build: {
    outDir: 'dist-mobile',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: 'assets/app-[hash].js',
        chunkFileNames: 'assets/chunk-[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
});
