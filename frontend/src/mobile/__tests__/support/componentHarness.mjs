import { register } from 'node:module';
import { dirname, resolve as resolvePath } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const SUPPORT_DIRECTORY = dirname(fileURLToPath(import.meta.url));
const MOBILE_DIRECTORY = resolvePath(SUPPORT_DIRECTORY, '..', '..');

function createMemoryStorage() {
  const entries = new Map();
  return {
    getItem: (key) => (entries.has(key) ? entries.get(key) : null),
    setItem: (key, value) => entries.set(key, String(value)),
    removeItem: (key) => entries.delete(key),
    clear: () => entries.clear(),
    key: (index) => Array.from(entries.keys())[index] ?? null,
    get length() {
      return entries.size;
    },
  };
}

function createEventTarget() {
  const listeners = new Map();
  return {
    addEventListener(type, listener) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type).add(listener);
    },
    removeEventListener(type, listener) {
      listeners.get(type)?.delete(listener);
    },
    dispatchEvent(event) {
      listeners.get(event.type)?.forEach((listener) => listener(event));
      return true;
    },
  };
}

function installBrowserGlobals() {
  if (globalThis.window) return;

  const documentTarget = createEventTarget();
  const fakeDocument = {
    ...documentTarget,
    visibilityState: 'visible',
    hidden: false,
    body: { style: {}, classList: { add() {}, remove() {} }, appendChild() {}, removeChild() {} },
    documentElement: { style: { setProperty() {}, removeProperty() {} }, classList: { add() {}, remove() {} } },
    createElement: () => ({ style: {}, setAttribute() {}, click() {}, remove() {}, appendChild() {} }),
    querySelector: () => null,
    getElementById: () => null,
  };

  const windowTarget = createEventTarget();
  const fakeWindow = {
    ...windowTarget,
    location: { hostname: 'localhost', origin: 'https://localhost', href: 'https://localhost/', protocol: 'https:', hash: '' },
    localStorage: createMemoryStorage(),
    sessionStorage: createMemoryStorage(),
    document: fakeDocument,
    navigator: { userAgent: 'node-test', onLine: true },
    confirm: () => true,
    alert: () => {},
    open: () => null,
    setTimeout,
    clearTimeout,
    setInterval,
    clearInterval,
    requestAnimationFrame: (callback) => setTimeout(() => callback(Date.now()), 0),
    cancelAnimationFrame: (handle) => clearTimeout(handle),
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    innerWidth: 390,
    innerHeight: 844,
    visualViewport: null,
    history: { back() {}, pushState() {}, replaceState() {} },
    getComputedStyle: () => ({ getPropertyValue: () => '' }),
  };
  fakeWindow.window = fakeWindow;

  globalThis.window = fakeWindow;
  globalThis.document = fakeDocument;
  globalThis.localStorage = fakeWindow.localStorage;
  globalThis.sessionStorage = fakeWindow.sessionStorage;
  globalThis.requestAnimationFrame = fakeWindow.requestAnimationFrame;
  globalThis.cancelAnimationFrame = fakeWindow.cancelAnimationFrame;
  if (!globalThis.navigator) globalThis.navigator = fakeWindow.navigator;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
}

function toAbsoluteMobilePath(relativePath) {
  return resolvePath(MOBILE_DIRECTORY, relativePath);
}

let isRegistered = false;

export function registerComponentLoader({ moduleOverrides = {} } = {}) {
  if (isRegistered) return;
  isRegistered = true;

  const absoluteOverrides = Object.fromEntries(
    Object.entries(moduleOverrides).map(([target, replacement]) => [
      toAbsoluteMobilePath(target),
      toAbsoluteMobilePath(replacement),
    ])
  );

  installBrowserGlobals();
  register('./jsxLoaderHooks.mjs', import.meta.url, { data: { moduleOverrides: absoluteOverrides } });
}

export async function importMobileModule(relativePath) {
  registerComponentLoader();
  return import(pathToFileURL(toAbsoluteMobilePath(relativePath)).href);
}

export async function loadRenderer() {
  registerComponentLoader();
  const [{ default: React }, { default: TestRenderer }] = await Promise.all([
    import('react'),
    import('react-test-renderer'),
  ]);
  return { React, TestRenderer, act: TestRenderer.act };
}

export async function renderElement(element) {
  const { TestRenderer, act } = await loadRenderer();
  let renderer;
  await act(async () => {
    renderer = TestRenderer.create(element);
  });
  return renderer;
}

export async function flushEffects(milliseconds = 0) {
  const { act } = await loadRenderer();
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, milliseconds));
  });
}

export function textOf(node) {
  if (node === null || node === undefined) return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join('');
  if (typeof node.toJSON === 'function') return textOf(node.toJSON());
  return textOf(node.children || []);
}

export function findAllByText(renderer, text) {
  return renderer.root.findAll(
    (instance) => typeof instance.type === 'string' && textOf(instance.children).includes(text)
  );
}

export function findButtonByText(renderer, text) {
  const matches = renderer.root.findAll(
    (instance) => instance.type === 'button' && textOf(instance.children).includes(text)
  );
  return matches[0] || null;
}

export async function press(instance, eventOverrides = {}) {
  const { act } = await loadRenderer();
  const event = { preventDefault() {}, stopPropagation() {}, target: {}, currentTarget: {}, ...eventOverrides };
  await act(async () => {
    await instance.props.onClick(event);
  });
}
