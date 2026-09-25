// @ts-check
const { test, expect } = require('@playwright/test');

const BASE_URL = process.env.TEST_URL || 'http://localhost:80';
const ADMIN_USER = 'admin';
const ADMIN_PASS = 'admin_password'; // Replace if you changed the local dev password

test.describe('NETRAKSH Live Deployment UI Verification', () => {

  test('Authentication & Dashboard Routing', async ({ page }) => {
    // 1. Authentication Check
    await page.goto(`${BASE_URL}/login`);
    
    await page.getByPlaceholder('Username').fill(ADMIN_USER);
    await page.getByPlaceholder('Password').fill(ADMIN_PASS);
    await page.getByRole('button', { name: 'Sign in' }).click();

    // Verify successful routing to Dashboard
    await expect(page).toHaveURL(`${BASE_URL}/`);
    await expect(page.locator('h1').filter({ hasText: 'NETRAKSH' }).first()).toBeVisible();
  });

  test('Bug Regression & Core Telemetry', async ({ page }) => {
    // Navigate and login
    await page.goto(`${BASE_URL}/login`);
    await page.getByPlaceholder('Username').fill(ADMIN_USER);
    await page.getByPlaceholder('Password').fill(ADMIN_PASS);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await expect(page).toHaveURL(`${BASE_URL}/`);

    // 2. Bug Regression Check (Ensure SUPER DEBUG OVERLAY is gone)
    const debugOverlay = page.locator('text=[SUPER DEBUG OVERLAY]');
    await expect(debugOverlay).toHaveCount(0);

    // 3. WebSocket / Telemetry Check
    // The "LIVE" indicator appears when the WebSocket is connected and streaming data
    const liveIndicator = page.getByText('LIVE', { exact: true });
    await expect(liveIndicator).toBeVisible({ timeout: 10000 });

    // 4. SVG Tracking Check
    // Verify that the <svg> overlay and tracking <rect> elements exist on the video feed
    const svgOverlay = page.locator('.video-overlay-svg');
    await expect(svgOverlay).toBeVisible();
    
    // We expect at least one <rect> (bounding box) to eventually render if the edge is sending targets
    // We use a timeout in case telemetry takes a few seconds to ingest
    const trackRect = page.locator('.video-overlay-svg rect').first();
    await expect(trackRect).toBeAttached({ timeout: 15000 });
  });

  test('Navigation Check', async ({ page }) => {
    // Login
    await page.goto(`${BASE_URL}/login`);
    await page.getByPlaceholder('Username').fill(ADMIN_USER);
    await page.getByPlaceholder('Password').fill(ADMIN_PASS);
    await page.getByRole('button', { name: 'Sign in' }).click();

    // 5. Navigation Check (Sidebar traversal)
    // Evidence Vault
    await page.locator('a[title="Evidence Vault"]').click();
    await expect(page).toHaveURL(`${BASE_URL}/evidence`);
    
    // Watchlist
    await page.locator('a[title="Watchlist & Identity"]').click();
    await expect(page).toHaveURL(`${BASE_URL}/watchlist`);
    
    // Geospatial Map
    await page.locator('a[title="Geospatial Map"]').click();
    await expect(page).toHaveURL(`${BASE_URL}/map`);
    
    // Command Analytics
    await page.locator('a[title="Command Analytics"]').click();
    await expect(page).toHaveURL(`${BASE_URL}/analytics`);
    
    // Audit Ledger
    await page.locator('a[title="Audit Ledger"]').click();
    await expect(page).toHaveURL(`${BASE_URL}/audit`);
  });

  test('Network Resilience Check', async ({ page, context }) => {
    // Login
    await page.goto(`${BASE_URL}/login`);
    await page.getByPlaceholder('Username').fill(ADMIN_USER);
    await page.getByPlaceholder('Password').fill(ADMIN_PASS);
    await page.getByRole('button', { name: 'Sign in' }).click();
    
    // Wait for the UI to stabilize
    await expect(page.locator('text=NETRAKSH').first()).toBeVisible();

    // 6. Network Resilience Check
    // Simulate a WebSocket drop or backend crash by going offline
    await context.setOffline(true);

    // The tactical UI overlay should render
    const severedText = page.getByText('Critical Link Severed', { exact: true });
    await expect(severedText).toBeVisible();
    
    // Bring it back online and ensure it recovers
    await context.setOffline(false);
    await expect(severedText).not.toBeVisible({ timeout: 35000 }); // Backoff might take up to 30s
  });

});
