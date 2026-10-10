import { defineConfig, devices } from '@playwright/test'

// Pruebas del panel en un navegador real contra la app de verdad (API + build), con datos simulados:
//   npm run build && npm run e2e
// El servidor (tests/e2e_server.py) usa una BD temporal y proveedores falsos (sin red).
// FW_CHROMIUM=/ruta/a/chrome para usar un Chromium propio en lugar del de `npx playwright install`.
const PORT = 8765

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    locale: 'es-ES',
    timezoneId: 'Europe/Madrid',
    trace: 'retain-on-failure',
    launchOptions: { executablePath: process.env.FW_CHROMIUM || undefined },
  },
  projects: [
    { name: 'escritorio', use: { ...devices['Desktop Chrome'] } },
    { name: 'movil', use: { ...devices['Pixel 7'] }, grep: /@movil/ },
  ],
  webServer: {
    command: `python -m tests.e2e_server ${PORT}`,
    cwd: '..',
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
})
