import assert from 'node:assert/strict';
import { afterEach, beforeEach, test } from 'node:test';
import {
  findAllByText,
  findButtonByText,
  flushEffects,
  importMobileModule,
  loadRenderer,
  press,
  renderElement,
  textOf,
} from './support/componentHarness.mjs';

const CURRENT_USER_ID = '7';
const OTHER_USER_ID = 8;
const IMAGE_URL = 'https://s3.test/blogs/user_7/image.png?signature=1';
const PDF_URL = 'https://s3.test/blogs/user_7/notes.pdf?signature=1';

const { React, act } = await loadRenderer();
const { MemoryRouter, Route, Routes } = await import('react-router-dom');
const apiModule = await importMobileModule('../services/api.js');
const { knowledgeService } = apiModule;
const apiClient = apiModule.default;
const backDismiss = await importMobileModule('platform/backDismissStack.js');
const { default: KnowledgeScreen } = await importMobileModule('screens/knowledge/KnowledgeScreen.jsx');
const { default: KnowledgeDetailScreen } = await importMobileModule('screens/knowledge/KnowledgeDetailScreen.jsx');
const { default: KnowledgeCreateScreen } = await importMobileModule('screens/knowledge/KnowledgeCreateScreen.jsx');

const originalKnowledgeService = { ...knowledgeService };
const originalApiPost = apiClient.post;
const originalWindowOpen = window.open;
const mountedRenderers = [];

function samplePost(overrides = {}) {
  return {
    blogId: 11,
    title: '미적분 정리',
    content: '적분 ∫₀¹ x² dx = 1/3 정리',
    authorId: OTHER_USER_ID,
    authorNickname: '다른학생',
    createdAt: '2026-09-27T10:30:00',
    likeCount: 4,
    likedByCurrentUser: false,
    imagePresignedUrl: null,
    pdfPresignedUrl: null,
    comments: [],
    ...overrides,
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

async function renderAt(path) {
  const element = React.createElement(
    MemoryRouter,
    { initialEntries: [path] },
    React.createElement(
      Routes,
      null,
      React.createElement(Route, { path: '/knowledge', element: React.createElement(KnowledgeScreen) }),
      React.createElement(Route, { path: '/knowledge/new', element: React.createElement(KnowledgeCreateScreen) }),
      React.createElement(Route, { path: '/knowledge/:blogId', element: React.createElement(KnowledgeDetailScreen) })
    )
  );
  const renderer = await renderElement(element);
  mountedRenderers.push(renderer);
  await flushEffects();
  return renderer;
}

function findButtonByLabel(renderer, labelPrefix) {
  return (
    renderer.root.findAll(
      (instance) =>
        instance.type === 'button' && String(instance.props['aria-label'] || '').startsWith(labelPrefix)
    )[0] || null
  );
}

function likeButtonOf(renderer) {
  return renderer.root.find((instance) => instance.type === 'button' && 'aria-pressed' in instance.props);
}

function likeSnapshot(renderer) {
  const button = likeButtonOf(renderer);
  const heart = button.findAll((instance) => instance.type === 'svg')[0];
  return {
    pressed: button.props['aria-pressed'],
    count: textOf(button.children),
    fill: heart.props.fill,
  };
}

function viewerOf(renderer) {
  return renderer.root.findAll(
    (instance) => instance.type === 'div' && instance.props['aria-label'] === '이미지 보기'
  )[0] || null;
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem('userId', CURRENT_USER_ID);
  Object.assign(knowledgeService, originalKnowledgeService);
  apiClient.post = originalApiPost;
  window.open = originalWindowOpen;
});

afterEach(async () => {
  while (mountedRenderers.length > 0) {
    const renderer = mountedRenderers.pop();
    await act(async () => renderer.unmount());
  }
  assert.equal(backDismiss.pendingDismissCount(), 0);
});

test('T33 tapping a post image opens the fullscreen viewer with the original image, zoom and pinch', async () => {
  knowledgeService.getPostDetail = async () => samplePost({ imagePresignedUrl: IMAGE_URL });
  const renderer = await renderAt('/knowledge/11');

  assert.equal(viewerOf(renderer), null);
  await press(findButtonByLabel(renderer, '이미지 크게 보기'));

  const viewer = viewerOf(renderer);
  assert.ok(viewer, 'viewer dialog should open');
  const image = viewer.find((instance) => instance.type === 'img');
  assert.equal(image.props.src, IMAGE_URL);
  assert.match(image.props.style.transform, /scale\(1\)/);

  await press(findButtonByLabel(renderer, '확대'));
  assert.match(viewer.find((instance) => instance.type === 'img').props.style.transform, /scale\(1\.5\)/);

  await press(findButtonByLabel(renderer, '원래 크기'));
  const stage = viewer.find((instance) => typeof instance.props.onPointerDown === 'function');
  const pointer = (pointerId, clientX) => ({ pointerId, clientX, clientY: 100, currentTarget: {} });
  await act(async () => {
    stage.props.onPointerDown(pointer(1, 100));
    stage.props.onPointerDown(pointer(2, 200));
  });
  await act(async () => stage.props.onPointerMove(pointer(2, 300)));
  assert.match(viewer.find((instance) => instance.type === 'img').props.style.transform, /scale\(2\)/);

  await press(findButtonByLabel(renderer, '이미지 닫기'));
  assert.equal(viewerOf(renderer), null);
});

test('T33 feed image also opens the viewer', async () => {
  knowledgeService.getPosts = async () => [samplePost({ imagePresignedUrl: IMAGE_URL })];
  const renderer = await renderAt('/knowledge');

  await press(findButtonByLabel(renderer, '이미지 크게 보기'));
  assert.equal(viewerOf(renderer).find((instance) => instance.type === 'img').props.src, IMAGE_URL);
});

test('T34 Android back (dismissTopLayer) closes only the viewer, then only the report sheet', async () => {
  knowledgeService.getPostDetail = async () =>
    samplePost({
      imagePresignedUrl: IMAGE_URL,
      comments: [{ commentId: 5, authorId: OTHER_USER_ID, authorNickname: '다른학생', content: '좋은 글' }],
    });
  const renderer = await renderAt('/knowledge/11');

  await press(findButtonByLabel(renderer, '이미지 크게 보기'));
  assert.equal(backDismiss.pendingDismissCount(), 1);

  let handled;
  await act(async () => {
    handled = backDismiss.dismissTopLayer();
  });
  assert.equal(handled, true);
  assert.equal(viewerOf(renderer), null);
  assert.ok(textOf(renderer.toJSON()).includes('미적분 정리'), 'detail page must stay');

  await press(findButtonByLabel(renderer, '댓글 신고'));
  assert.ok(textOf(renderer.toJSON()).includes('신고 사유'));
  await act(async () => {
    handled = backDismiss.dismissTopLayer();
  });
  assert.equal(handled, true);
  assert.equal(textOf(renderer.toJSON()).includes('신고 사유'), false);
  assert.ok(textOf(renderer.toJSON()).includes('미적분 정리'));

  assert.equal(backDismiss.dismissTopLayer(), false, 'with no layer open, back falls through to navigation');
});

test('T35 like turns the outline heart into a filled heart and adds one', async () => {
  const request = deferred();
  const calls = [];
  knowledgeService.getPostDetail = async () => samplePost();
  knowledgeService.toggleLike = (blogId) => {
    calls.push(blogId);
    return request.promise;
  };
  const renderer = await renderAt('/knowledge/11');

  assert.deepEqual(likeSnapshot(renderer), { pressed: false, count: '4', fill: 'none' });
  await press(likeButtonOf(renderer));
  assert.deepEqual(likeSnapshot(renderer), { pressed: true, count: '5', fill: 'currentColor' });

  await act(async () => request.resolve(samplePost({ likeCount: 5, likedByCurrentUser: true })));
  assert.deepEqual(likeSnapshot(renderer), { pressed: true, count: '5', fill: 'currentColor' });
  assert.deepEqual(calls, [11]);
});

test('R-LIKE the liked heart icon overrides the global muted .lucide color', async () => {
  const { readFile } = await import('node:fs/promises');
  const stylesheetUrl = new URL('../screens/knowledge/knowledge.css', import.meta.url);
  const globalUrl = new URL('../../index.css', import.meta.url);
  const [knowledgeCss, globalCss] = await Promise.all([readFile(stylesheetUrl, 'utf8'), readFile(globalUrl, 'utf8')]);

  const rules = [...knowledgeCss.matchAll(/([^{}]+)\{([^}]*)\}/g)].map(([, selector, body]) => ({
    selectors: selector.split(',').map((part) => part.trim()),
    body,
  }));
  const likedIconRule = rules.find(
    (rule) =>
      rule.selectors.some((selector) => /\.knowledge-action\.is-liked\s+\.lucide$/.test(selector)) &&
      /color:\s*inherit/.test(rule.body)
  );

  assert.match(globalCss, /\.lucide\s*\{\s*color:\s*var\(--color-text-muted\)/);
  assert.ok(likedIconRule, 'liked heart must inherit the danger color instead of the global muted icon color');
});

test('T36 unlike returns to the outline heart and subtracts one', async () => {
  knowledgeService.getPostDetail = async () => samplePost({ likeCount: 5, likedByCurrentUser: true });
  knowledgeService.toggleLike = async () => samplePost({ likeCount: 4, likedByCurrentUser: false });
  const renderer = await renderAt('/knowledge/11');

  assert.deepEqual(likeSnapshot(renderer), { pressed: true, count: '5', fill: 'currentColor' });
  await press(likeButtonOf(renderer));
  await flushEffects();
  assert.deepEqual(likeSnapshot(renderer), { pressed: false, count: '4', fill: 'none' });
});

test('T37 a failed like request rolls back to the previous state and explains why', async () => {
  const request = deferred();
  knowledgeService.getPostDetail = async () => samplePost();
  knowledgeService.toggleLike = () => request.promise;
  const renderer = await renderAt('/knowledge/11');

  await press(likeButtonOf(renderer));
  assert.equal(likeSnapshot(renderer).count, '5');

  await act(async () => request.reject({ response: { status: 500 } }));
  await flushEffects();
  assert.deepEqual(likeSnapshot(renderer), { pressed: false, count: '4', fill: 'none' });
  assert.ok(textOf(renderer.toJSON()).includes('좋아요를 반영하지 못했습니다'));
});

test('like taps while a request is pending are ignored instead of exploding the count', async () => {
  const request = deferred();
  let callCount = 0;
  knowledgeService.getPosts = async () => [samplePost()];
  knowledgeService.toggleLike = () => {
    callCount += 1;
    return request.promise;
  };
  const renderer = await renderAt('/knowledge');

  await press(likeButtonOf(renderer));
  await press(likeButtonOf(renderer));
  await press(likeButtonOf(renderer));
  assert.equal(callCount, 1);
  assert.deepEqual(likeSnapshot(renderer), { pressed: true, count: '5', fill: 'currentColor' });

  await act(async () => request.resolve(samplePost({ likeCount: 5, likedByCurrentUser: true })));
  await press(likeButtonOf(renderer));
  assert.equal(callCount, 2, 'taps are accepted again once the request settles');
});

test('returning to the feed re-syncs like state from the server', async () => {
  let serverPost = samplePost();
  knowledgeService.getPosts = async () => [serverPost];
  const renderer = await renderAt('/knowledge');
  assert.equal(likeSnapshot(renderer).count, '4');

  serverPost = samplePost({ likeCount: 9, likedByCurrentUser: true });
  await act(async () => {
    document.dispatchEvent({ type: 'visibilitychange' });
  });
  await flushEffects();
  assert.deepEqual(likeSnapshot(renderer), { pressed: true, count: '9', fill: 'currentColor' });
});

test('T38 reporting another user comment sends the reason to the real report API', async () => {
  const reports = [];
  knowledgeService.getPostDetail = async () =>
    samplePost({
      comments: [
        { commentId: 5, authorId: OTHER_USER_ID, authorNickname: '다른학생', content: 'x'.repeat(400) },
      ],
    });
  knowledgeService.reportComment = async (commentId, payload) => {
    reports.push({ commentId, payload });
    return { reportId: 1 };
  };
  const renderer = await renderAt('/knowledge/11');

  assert.equal(findButtonByLabel(renderer, '내 댓글 관리'), null, 'others comment has no delete action');
  await press(findButtonByLabel(renderer, '댓글 신고'));

  const reasons = renderer.root.findAll((instance) => instance.props.role === 'radio').map((node) => textOf(node.children));
  assert.deepEqual(reasons, ['스팸', '욕설·비방', '부적절한 내용', '기타']);
  assert.equal(findButtonByText(renderer, '신고하기').props.disabled, true, 'reason is required');

  await press(findButtonByText(renderer, '욕설·비방'));
  await press(findButtonByText(renderer, '신고하기'));
  await flushEffects();

  assert.deepEqual(reports, [{ commentId: 5, payload: { reason: 'ABUSE', details: '' } }]);
  assert.ok(textOf(renderer.toJSON()).includes('신고가 접수되었습니다'));
  assert.equal(textOf(renderer.toJSON()).includes('신고 사유'), false);
});

test('T38 a rejected report shows the server reason and never a fake success', async () => {
  knowledgeService.getPostDetail = async () =>
    samplePost({ comments: [{ commentId: 5, authorId: OTHER_USER_ID, authorNickname: '다른학생', content: 'hi' }] });
  knowledgeService.reportComment = async () => {
    throw { response: { status: 409, data: { message: '이미 해당 댓글을 신고하셨습니다.' } } };
  };
  const renderer = await renderAt('/knowledge/11');

  await press(findButtonByLabel(renderer, '댓글 신고'));
  await press(findButtonByText(renderer, '스팸'));
  await press(findButtonByText(renderer, '신고하기'));
  await flushEffects();

  const text = textOf(renderer.toJSON());
  assert.ok(text.includes('이미 신고한 댓글입니다.'));
  assert.equal(text.includes('신고가 접수되었습니다'), false);
});

test('T38 own comment offers delete, which calls the delete API and refreshes', async () => {
  const deleted = [];
  let comments = [{ commentId: 6, authorId: Number(CURRENT_USER_ID), authorNickname: '나', content: '내 댓글' }];
  knowledgeService.getPostDetail = async () => samplePost({ comments });
  knowledgeService.deleteComment = async (blogId, commentId) => {
    deleted.push([blogId, commentId]);
    comments = [];
  };
  const renderer = await renderAt('/knowledge/11');

  assert.equal(findButtonByLabel(renderer, '댓글 신고'), null, 'own comment cannot be reported');
  await press(findButtonByLabel(renderer, '내 댓글 관리'));
  await press(findAllByText(renderer, '삭제').find((node) => node.type === 'button'));
  await flushEffects();

  assert.deepEqual(deleted, [['11', 6]]);
  assert.equal(textOf(renderer.toJSON()).includes('내 댓글'), false);
  assert.ok(textOf(renderer.toJSON()).includes('댓글 0'));
});

test('T39 image upload sends multipart with the backend field names and the re-fetched post shows the served image', async () => {
  const requests = [];
  apiClient.post = async (url, body, config) => {
    requests.push({ url, body, config });
    return { data: samplePost({ blogId: 99 }) };
  };
  knowledgeService.getPostDetail = async (blogId) =>
    samplePost({ blogId: Number(blogId), imagePresignedUrl: IMAGE_URL, pdfPresignedUrl: PDF_URL });
  const renderer = await renderAt('/knowledge/new');

  const inputs = renderer.root.findAll((instance) => instance.type === 'input' && instance.props.type === 'file');
  const imageInput = inputs.find((input) => input.props.accept.includes('image/png'));
  const pdfInput = inputs.find((input) => input.props.accept === 'application/pdf');
  assert.equal(imageInput.props.accept, 'image/jpeg,image/png,image/gif,image/webp');

  const [titleField, contentField] = renderer.root.findAll(
    (instance) => (instance.type === 'input' && instance.props.type !== 'file' && instance.props.type !== 'search') || instance.type === 'textarea'
  );
  const imageFile = new File(['png-bytes'], '수업 사진 1.png', { type: 'image/png' });
  const pdfFile = new File(['%PDF-1.4'], '정리 노트.pdf', { type: 'application/pdf' });

  await act(async () => {
    titleField.props.onChange({ target: { value: '제목' } });
    contentField.props.onChange({ target: { value: '본문' } });
    imageInput.props.onChange({ target: { files: [new File(['x'], 'photo.heic', { type: 'image/heic' })], value: '' } });
  });
  assert.ok(textOf(renderer.toJSON()).includes('JPG, PNG, GIF, WEBP 이미지만 첨부할 수 있습니다.'));

  await act(async () => {
    imageInput.props.onChange({ target: { files: [imageFile], value: '' } });
    pdfInput.props.onChange({ target: { files: [pdfFile], value: '' } });
  });

  const form = renderer.root.find((instance) => instance.type === 'form');
  await act(async () => form.props.onSubmit({ preventDefault() {} }));
  await flushEffects();

  assert.equal(requests.length, 1);
  const [{ url, body, config }] = requests;
  assert.equal(url, '/api/blogs');
  assert.ok(body instanceof FormData);
  assert.equal(body.get('title'), '제목');
  assert.equal(body.get('content'), '본문');
  assert.equal(body.get('image').name, '수업 사진 1.png');
  assert.equal(body.get('image').type, 'image/png');
  assert.equal(body.get('pdf').name, '정리 노트.pdf');
  assert.equal(config.headers['Content-Type'], 'multipart/form-data');

  const images = renderer.root.findAll((instance) => instance.type === 'img');
  assert.ok(images.some((image) => image.props.src === IMAGE_URL), 'detail shows the server image URL');
});

test('T40 PDF attachment is rendered from the post and opens with a fresh URL or inline preview', async () => {
  const freshUrl = `${PDF_URL}&fresh=1`;
  let detailCalls = 0;
  const opened = [];
  knowledgeService.getPostDetail = async () => {
    detailCalls += 1;
    return samplePost({ pdfPresignedUrl: detailCalls === 1 ? PDF_URL : freshUrl });
  };
  window.open = (url) => {
    opened.push(url);
    return null;
  };
  const renderer = await renderAt('/knowledge/11');

  assert.ok(textOf(renderer.toJSON()).includes('첨부 PDF'));
  await press(findButtonByText(renderer, '외부 앱으로 열기'));
  await flushEffects();
  assert.deepEqual(opened, [freshUrl]);

  await press(findButtonByText(renderer, 'PDF 미리보기'));
  const preview = renderer.root.findAll(
    (instance) => instance.type === 'section' && String(instance.props['aria-label'] || '').endsWith('원본 문서')
  );
  assert.equal(preview.length, 1);
  await press(findButtonByText(renderer, '미리보기 닫기'));
});
