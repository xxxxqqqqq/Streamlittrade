import {defineConfig} from '@playwright/test'

export default defineConfig({
  testDir:'./e2e',
  timeout:30000,
  retries:0,
  use:{
    baseURL:process.env.E2E_BASE_URL||'http://localhost:5173',
    trace:'retain-on-failure',
    screenshot:'only-on-failure',
    launchOptions:{
      executablePath:process.env.PLAYWRIGHT_EXECUTABLE_PATH,
      args:['--no-sandbox'],
    },
  },
  reporter:'list',
})
