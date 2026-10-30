import { defineConfig } from '@playwright/test';

// Automatic error-context snapshots can include connection form values even when tracing is disabled.
process.env.PLAYWRIGHT_NO_COPY_PROMPT = '1';
const port = Number(process.env.DOCKSIGHT_E2E_PREVIEW_PORT);

export default defineConfig({
  testDir: './live-tests',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 300_000,
  expect: { timeout: 15_000 },
  reporter: 'list',
  outputDir: '../.test-artifacts/live-browser',
  webServer: {
    command: `npm run preview -- --port ${port} --strictPort`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: false,
    timeout: 30_000,
  },
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    channel: 'chrome',
    viewport: { width: 1440, height: 1000 },
    locale: 'en-US',
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
});
