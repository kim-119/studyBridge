[FINAL ADD-ON 2] — candidate QA

Baseline: 958f013a. Existing mobile/auth/integration changes preserved in addon-final-integration.

- Node: 100 passed. Java: 402 passed / 67 suites. FastAPI count: 3 passed.
- Desktop / Chromium 360,393,430 / WebKit 393,430: canonical routing and Back, calendar/weekly, journal verified.
- Calendar widths: 360,375,390,393,402,412,430,440; 7 columns, page overflow 0, date input fits.
- Actual AI: Desktop 1280 / Chromium 393 / WebKit 393 each 3 selected, 3 requested, 3 backend received, 3 AI requested, 3 AI returned, 3 rendered. No response fixture or original-question fallback in count-live final run.
- GENERAL/CAM timer: existing server session, refresh restore, heartbeat, end and stats assertions passed.
- Profile controlled reproduction: PUT /api/users/profile with >255-character photoUrl: baseline 500, candidate 200, existing photo preserved. Token never included in evidence.
- Reports: authenticated principal-scoped paginated query; A sees own reports, B cannot see A; post/comment deletion retains report with safe fallback. Existing duplicate rejection retained.
- Memo browser checks use actual DOM typing and synthetic composition events. Native OS Korean IME remains device acceptance.

See sibling JSON evidence. Production release and final SHA are recorded separately after deployment.
