import { defineConfig } from '@playwright/test';
// Croatian is the primary UI language; the browser announces it like a Croatian visitor's would.
export default defineConfig({testDir:'tests/web/browser',workers:1,use:{baseURL:'http://127.0.0.1:55484',browserName:'chromium',locale:'hr-HR'},reporter:'list',outputDir:'test-results'});
