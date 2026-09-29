import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { flushEffects, importMobileModule, loadRenderer, renderElement } from './support/componentHarness.mjs';

const TEST_DIRECTORY = dirname(fileURLToPath(import.meta.url));
const REPOSITORY_ROOT = resolve(TEST_DIRECTORY, '..', '..', '..', '..');
const ANDROID_MAIN = join(REPOSITORY_ROOT, 'android', 'app', 'src', 'main');
const RESOURCE_ROOT = join(ANDROID_MAIN, 'res');
const MOBILE_CSS = join(TEST_DIRECTORY, '..', 'mobile.css');

const DENSITY_SCALE = { ldpi: 0.75, mdpi: 1, hdpi: 1.5, xhdpi: 2, xxhdpi: 3, xxxhdpi: 4 };
const SPLASH_ICON_CANVAS_DP = 288;
const SPLASH_ICON_SAFE_CIRCLE_DP = 192;
const STRETCHING_SCALE_TYPES = ['FIT_XY', 'CENTER_CROP', 'MATRIX'];
const TESTED_SCREENS_DP = [
  { name: 'phone 360', width: 360, height: 780 },
  { name: 'phone 390', width: 390, height: 844 },
  { name: 'phone 412', width: 412, height: 915 },
  { name: 'BlueStacks landscape 1600x900 @320dpi', width: 800, height: 450 },
  { name: 'BlueStacks portrait 900x1600 @320dpi', width: 450, height: 800 },
];

function readText(path) {
  return readFileSync(path, 'utf8');
}

function parseAttributes(source) {
  const attributes = {};
  for (const match of source.matchAll(/([\w:]+)\s*=\s*"([^"]*)"/g)) attributes[match[1]] = match[2];
  return attributes;
}

function parseElements(xml, tagName) {
  const pattern = new RegExp(`<${tagName}\\b([^>]*?)\\/?>`, 'g');
  return Array.from(xml.matchAll(pattern), (match) => parseAttributes(match[1]));
}

function parseStyles(xml) {
  const styles = {};
  for (const match of xml.matchAll(/<style\b([^>]*)>([\s\S]*?)<\/style>/g)) {
    const { name, parent } = parseAttributes(match[1]);
    const items = {};
    for (const item of match[2].matchAll(/<item\s+name="([^"]+)"\s*>([\s\S]*?)<\/item>/g)) {
      items[item[1]] = item[2].trim();
    }
    styles[name] = { parent, items };
  }
  return styles;
}

function launchThemeName() {
  const manifest = readText(join(ANDROID_MAIN, 'AndroidManifest.xml'));
  const launcher = parseElements(manifest, 'activity').find((activity) => activity['android:name'] === '.MainActivity');
  return launcher['android:theme'].replace('@style/', '');
}

function drawableVariants(resourceName) {
  return readdirSync(RESOURCE_ROOT, { withFileTypes: true })
    .filter((entry) => entry.isDirectory() && entry.name.startsWith('drawable'))
    .flatMap((directory) =>
      readdirSync(join(RESOURCE_ROOT, directory.name))
        .filter((file) => file.replace(extname(file), '') === resourceName)
        .map((file) => ({ folder: directory.name, path: join(RESOURCE_ROOT, directory.name, file) }))
    );
}

function drawableName(reference) {
  return reference.replace('@drawable/', '');
}

function pngSize(path) {
  const bytes = readFileSync(path);
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

function densityScaleOf(folder) {
  const qualifier = folder.split('-').find((part) => DENSITY_SCALE[part]);
  return qualifier ? DENSITY_SCALE[qualifier] : 1;
}

function bitmapSizesInDp(resourceName) {
  return drawableVariants(resourceName).map(({ folder, path }) => {
    assert.equal(extname(path), '.png', `${folder}/${resourceName} must be a bitmap`);
    const pixels = pngSize(path);
    const scale = densityScaleOf(folder);
    return { folder, pixels, width: pixels.width / scale, height: pixels.height / scale };
  });
}

function assertCenteredLayerDrawable(resourceName) {
  const variants = drawableVariants(resourceName);
  assert.ok(variants.length > 0, `@drawable/${resourceName} must exist`);

  const logoReferences = new Set();
  for (const { folder, path } of variants) {
    assert.equal(extname(path), '.xml', `${folder}/${resourceName} must not be a full-bleed bitmap`);
    const xml = readText(path);
    const bitmaps = parseElements(xml, 'bitmap');
    assert.ok(bitmaps.length > 0, `${folder}/${resourceName} must draw the logo as a bitmap`);

    for (const bitmap of bitmaps) {
      const gravity = (bitmap['android:gravity'] || '').split('|');
      assert.ok(gravity.includes('center'), `${folder}/${resourceName} logo must be centered`);
      assert.ok(!gravity.some((value) => value.startsWith('fill')), `${folder}/${resourceName} logo must not fill`);
      logoReferences.add(drawableName(bitmap['android:src']));
    }
  }
  return [...logoReferences];
}

test('T41 스플래시 리소스 체인이 로고 비율을 유지하고 가운데 배치한다', () => {
  const styles = parseStyles(readText(join(RESOURCE_ROOT, 'values', 'styles.xml')));
  const launchTheme = styles[launchThemeName()];

  assert.equal(launchTheme.parent, 'Theme.SplashScreen');
  assert.equal(launchTheme.items['android:background'], undefined, 'theme-wide background stretches the splash');
  assert.equal(launchTheme.items['android:windowBackground'], undefined);
  assert.equal(launchTheme.items.postSplashScreenTheme, '@style/AppTheme.NoActionBar');

  const iconName = drawableName(launchTheme.items.windowSplashScreenAnimatedIcon);
  const iconXml = readText(drawableVariants(iconName)[0].path);
  const canvas = parseElements(iconXml, 'item').find((item) => item['android:width']);
  assert.equal(canvas['android:width'], `${SPLASH_ICON_CANVAS_DP}dp`);
  assert.equal(canvas['android:height'], `${SPLASH_ICON_CANVAS_DP}dp`);

  const capacitorConfig = JSON.parse(readText(join(REPOSITORY_ROOT, 'capacitor.config.json')));
  const splashConfig = capacitorConfig.plugins.SplashScreen;
  const pluginResourceName = splashConfig.androidSplashResourceName || 'splash';
  assert.ok(splashConfig.androidScaleType, 'plugin default FIT_XY stretches the splash');
  assert.ok(!STRETCHING_SCALE_TYPES.includes(splashConfig.androidScaleType));

  const logoNames = new Set([...assertCenteredLayerDrawable(iconName), ...assertCenteredLayerDrawable(pluginResourceName)]);
  assert.equal(logoNames.size, 1, 'every splash path must draw the same logo bitmap');

  const [logoName] = logoNames;
  const logoSizes = bitmapSizesInDp(logoName);
  assert.ok(logoSizes.length > 0);

  for (const size of logoSizes) {
    const diagonal = Math.hypot(size.width, size.height);
    assert.ok(diagonal <= SPLASH_ICON_SAFE_CIRCLE_DP, `${size.folder} logo must fit the Android 12 icon circle`);
    for (const screen of TESTED_SCREENS_DP) {
      assert.ok(size.width <= screen.width * 0.6, `${screen.name}: logo too wide`);
      assert.ok(size.height <= screen.height * 0.4, `${screen.name}: logo too tall`);
    }
  }
});

test('T41 앱 내부 부팅 화면은 로고를 가로·세로 강제 크기로 늘리지 않는다', async () => {
  const { React } = await loadRenderer();
  const api = await importMobileModule('../services/api.js');
  api.bannerService.getMainBanner = async () => {
    throw new Error('offline in test');
  };
  const { default: MobileBoot } = await importMobileModule('MobileBoot.jsx');

  const renderer = await renderElement(React.createElement(MobileBoot, null, 'ready'));
  await flushEffects();
  const boot = renderer.root.find((instance) => instance.props.className === 'mobile-boot');
  const images = boot.findAll((instance) => instance.type === 'img');

  for (const image of images) {
    const style = image.props.style || {};
    const forcesBothSides = Boolean(style.width && style.height) || Boolean(image.props.width && image.props.height);
    assert.ok(!forcesBothSides || style.objectFit === 'contain', 'boot logo must keep its aspect ratio');
  }

  const bootRules = Array.from(readText(MOBILE_CSS).matchAll(/([^{}]*mobile-boot[^{}]*)\{([^}]*)\}/g));
  for (const [, selector, body] of bootRules) {
    const setsWidth = /(^|[\s;])width\s*:/.test(body);
    const setsHeight = /(^|[\s;])height\s*:/.test(body);
    const containsImage = /object-fit\s*:\s*contain/.test(body);
    assert.ok(!(setsWidth && setsHeight) || containsImage, `${selector.trim()} forces both width and height`);
  }

  renderer.unmount();
});
