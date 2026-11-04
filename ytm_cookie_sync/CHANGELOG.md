# Changelog

## 0.3.0
- First public version.
- Cookies are read directly from the Chromium profile database (no remote-controlled browser).
- Hand-over to Music Assistant through the official setup-flow API (MA validates premium itself and rolls back on failure).
- Music Assistant restart detection, deep check, limited retries with back-off.
- Sign-in panel (noVNC through ingress) starts automatically when a new sign-in is required; sign-in is finished automatically once new cookies are detected.
- English and German texts; amd64 and aarch64.
