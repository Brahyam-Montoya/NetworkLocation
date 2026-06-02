import fs from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";
import { config } from "../config.js";
import { ensureDir } from "../utils/fs.js";

const chromeUserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36";

const defaultSelectors = {
  loginEmail: [
    "input[type='email']",
    "input[type='text'][name='username']",
    "input[id='username']",
    "input[name='email']",
    "input[name='username']",
    "#email",
    "input[placeholder='Username']",
    "input[placeholder='Email']"
  ],
  loginPassword: [
    "input[type='password']",
    "input[name='password']",
    "#password",
    "input[placeholder='Password']"
  ],
  loginSubmit: [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('LOG IN')",
    "button:has-text('Login')",
    "button:has-text('Log in')",
    "button:has-text('Sign in')"
  ],
  dashboardSkipLink: [
    "text=skip this step",
    "a:has-text('skip this step')"
  ],
  dashboardDismissLink: [
    "text=Don't show me this anymore",
    "a:has-text(\"Don't show me this anymore\")"
  ],
  policiesMenu: [
    "a.main-nav-item--inspection",
    "text=Policies"
  ],
  policiesNetworkLink: [
    "a[href='#/profile-network-location']",
    "a.secondary-nav-item--profile-network-location",
    "text=Network"
  ],
  newNetworkLocationButton: [
    "button:has-text('NEW NETWORK LOCATION')",
    "button:has-text('New Network Location')",
    "text=NEW NETWORK LOCATION",
    "text=New Network Location",
    "button.ns-btn:has-text('NEW NETWORK LOCATION')",
    "button.ns-btn-primary:has-text('NEW NETWORK LOCATION')",
    "a:has-text('NEW NETWORK LOCATION')",
    "text=NEW NETWORK LOCATION",
    "text=New Network Location"
  ],
  multipleObjectsOption: [
    "text=Multiple Objects",
    "a:has-text('Multiple Objects')",
    "button:has-text('Multiple Objects')"
  ],
  uploadModal: [
    "text=Upload Network Locations",
    ".modal-content",
    ".ns-modal-content"
  ],
  nameInput: [
    "input[name='name']",
    "input[placeholder*='Name']",
    "input[aria-label*='Name']"
  ],
  fileInput: [
    ".modal-content input[type='file']",
    ".ns-modal-content input[type='file']",
    "input[type='file']"
  ],
  selectFileButton: [
    "button:has-text('SELECT FILE')",
    "text=SELECT FILE"
  ],
  uploadButton: [
    ".modal-content button:has-text('UPLOAD')",
    ".ns-modal-content button:has-text('UPLOAD')",
    "button:has-text('UPLOAD')"
  ],
  saveButton: [
    "button:has-text('Save')",
    "button:has-text('Create')",
    "button:has-text('Submit')"
  ],
  successSignal: [
    "text=successfully",
    "text=created",
    "text=saved",
    ".toast-success"
  ]
};

function mergedSelectors() {
  const override = config.netskope.selectorsOverride || {};
  return Object.fromEntries(
    Object.entries(defaultSelectors).map(([key, value]) => {
      const customValue = override[key];
      if (!customValue) {
        return [key, value];
      }

      return [key, Array.isArray(customValue) ? customValue : [customValue]];
    })
  );
}

function resolvePortalUrl(baseUrl, route) {
  if (!route) {
    return baseUrl;
  }

  if (/^https?:\/\//i.test(route)) {
    return route;
  }

  const base = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
  const normalized = route.startsWith("/") ? route : `/${route}`;
  return `${base}${normalized}`;
}

async function firstVisible(page, candidates, timeoutMs = 3000) {
  for (const selector of candidates) {
    const locator = page.locator(selector);
    const count = await locator.count();

    if (count < 1) {
      continue;
    }

    for (let index = 0; index < count; index += 1) {
      const candidate = locator.nth(index);

      if (await candidate.isVisible().catch(() => false)) {
        return candidate;
      }

      await candidate.waitFor({ state: "visible", timeout: timeoutMs }).catch(() => null);

      if (await candidate.isVisible().catch(() => false)) {
        return candidate;
      }
    }
  }

  throw new Error(`No fue posible encontrar un elemento visible. Candidatos: ${candidates.join(", ")}`);
}

async function firstExisting(page, candidates) {
  for (const selector of candidates) {
    const locator = page.locator(selector);
    const count = await locator.count();
    if (count > 0) {
      return locator.first();
    }
  }

  throw new Error(`No fue posible encontrar un elemento. Candidatos: ${candidates.join(", ")}`);
}

async function waitForAnyVisible(page, candidates, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    for (const selector of candidates) {
      const locator = page.locator(selector);
      const count = await locator.count().catch(() => 0);

      for (let index = 0; index < count; index += 1) {
        const candidate = locator.nth(index);
        if (await candidate.isVisible().catch(() => false)) {
          return candidate;
        }
      }
    }

    await page.waitForTimeout(250);
  }

  throw new Error(`No fue posible encontrar un elemento visible. Candidatos: ${candidates.join(", ")}`);
}

async function waitForLoginReady(page, selectors, timeoutMs = 20000) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const loginInput = await firstVisible(page, selectors.loginEmail, 500).catch(() => null);
    if (loginInput) {
      return loginInput;
    }

    const invalidBrowserText = await page.getByText("Browser Not Supported", { exact: false }).isVisible().catch(() => false);
    if (invalidBrowserText) {
      throw new Error("Netskope bloqueo el navegador con un mensaje de Browser Not Supported.");
    }

    await page.waitForLoadState("domcontentloaded", { timeout: 1000 }).catch(() => null);
    await page.waitForTimeout(500);
  }

  throw new Error(`No fue posible encontrar un elemento visible. Candidatos: ${selectors.loginEmail.join(", ")}`);
}

async function captureEvidence(page, evidenceDir, label) {
  await ensureDir(evidenceDir);
  const filePath = path.join(evidenceDir, `${label}.png`);
  await page.screenshot({ path: filePath, fullPage: true });
  return filePath;
}

function sanitizeError(error) {
  return error instanceof Error ? error.message : String(error);
}

function safePageUrl(page) {
  try {
    return page.url();
  } catch {
    return "";
  }
}

async function setFileOnModal(page, selectors, filePath, debugLog) {
  const directFileInput = await firstExisting(page, selectors.fileInput).catch(() => null);

  if (directFileInput) {
    await directFileInput.setInputFiles(filePath);
    debugLog.actions.push({ step: "set-file-direct", file: filePath });
    return "direct";
  }

  const selectFileButton = await firstVisible(page, selectors.selectFileButton, 5000);
  const [fileChooser] = await Promise.all([
    page.waitForEvent("filechooser", { timeout: 10000 }),
    selectFileButton.click()
  ]);
  await fileChooser.setFiles(filePath);
  debugLog.actions.push({ step: "set-file-filechooser", file: filePath });
  return "filechooser";
}

async function dismissDashboardOnboarding(page, selectors, debugLog) {
  const skipLink = await firstVisible(page, selectors.dashboardSkipLink, 3000).catch(() => null);
  if (skipLink) {
    await skipLink.click().catch(() => null);
    await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => null);
    debugLog.actions.push({ step: "skip-dashboard-onboarding" });
  }

  const dismissLink = await firstVisible(page, selectors.dashboardDismissLink, 2000).catch(() => null);
  if (dismissLink) {
    await dismissLink.click().catch(() => null);
    await page.waitForTimeout(1000);
    debugLog.actions.push({ step: "dismiss-dashboard-message" });
  }
}

async function navigateThroughPoliciesMenu(page, selectors, debugLog) {
  const policiesMenu = await firstVisible(page, selectors.policiesMenu, 8000);
  await policiesMenu.click();
  await page.waitForTimeout(1500);
  debugLog.actions.push({ step: "open-policies-menu", url: safePageUrl(page) });

  const networkLink = await firstVisible(page, selectors.policiesNetworkLink, 10000);
  await networkLink.click();
  await page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => null);
  await page.waitForTimeout(1500);
  debugLog.actions.push({ step: "open-network-profile", url: safePageUrl(page) });
}

async function getPageDebugSnapshot(page) {
  try {
    return await page.evaluate(() => ({
      title: document.title,
      url: location.href,
      bodyText: document.body?.innerText?.slice(0, 1200) || "",
      inputCount: document.querySelectorAll("input").length
    }));
  } catch {
    return {
      title: "",
      url: safePageUrl(page),
      bodyText: "",
      inputCount: 0
    };
  }
}

export async function runNetskopeAutomation(run) {
  const selectors = mergedSelectors();
  const evidenceDir = path.join(config.logsDir, run.id);
  await ensureDir(evidenceDir);

  if (!config.netskope.user || !config.netskope.password) {
    throw new Error("Faltan NETSKOPE_USER o NETSKOPE_PASSWORD en el archivo .env");
  }

  let browser;

  try {
    browser = await chromium.launch({
      channel: "chrome",
      headless: config.netskope.headless
    });
  } catch {
    browser = await chromium.launch({
      headless: config.netskope.headless
    });
  }

  const context = await browser.newContext({
    userAgent: chromeUserAgent,
    viewport: { width: 1440, height: 900 },
    locale: "en-US"
  });
  await context.setExtraHTTPHeaders({
    "sec-ch-ua": "\"Chromium\";v=\"136\", \"Google Chrome\";v=\"136\", \"Not.A/Brand\";v=\"99\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\""
  });
  const page = await context.newPage();

  const result = {
    status: "failed",
    message: "",
    screenshots: [],
    logsPath: path.join(evidenceDir, "automation-log.json")
  };

  const debugLog = {
    runId: run.id,
    loginUrl: resolvePortalUrl(config.netskope.baseUrl, config.netskope.loginPath),
    networkLocationUrl: resolvePortalUrl(config.netskope.baseUrl, config.netskope.networkLocationPath),
    actions: []
  };

  try {
    const loginUrl = debugLog.loginUrl;
    await page.goto(loginUrl, { waitUntil: "domcontentloaded", timeout: 45000 });
    debugLog.actions.push({ step: "goto-login", url: await page.url() });

    const emailInput = await waitForLoginReady(page, selectors, 20000);
    await emailInput.fill(config.netskope.user);
    debugLog.actions.push({ step: "fill-email" });

    const passwordInput = await firstVisible(page, selectors.loginPassword);
    await passwordInput.fill(config.netskope.password);
    debugLog.actions.push({ step: "fill-password" });

    const submitButton = await firstVisible(page, selectors.loginSubmit);
    await Promise.all([
      page.waitForLoadState("networkidle", { timeout: 45000 }).catch(() => null),
      submitButton.click()
    ]);
    debugLog.actions.push({ step: "submit-login", url: await page.url() });
    result.screenshots.push(await captureEvidence(page, evidenceDir, "01-after-login"));

    const invalidLoginMessage = page.getByText("Invalid username or password", { exact: false });
    if (await invalidLoginMessage.isVisible().catch(() => false)) {
      throw new Error("Netskope rechazo el login: Invalid username or password.");
    }

    await dismissDashboardOnboarding(page, selectors, debugLog);
    await navigateThroughPoliciesMenu(page, selectors, debugLog);
    result.screenshots.push(await captureEvidence(page, evidenceDir, "02-network-location"));

    const newButton = await firstVisible(page, selectors.newNetworkLocationButton, 6000);
    await newButton.click();
    debugLog.actions.push({ step: "open-new-network-location" });

    const multipleObjects = await firstVisible(page, selectors.multipleObjectsOption, 6000);
    await multipleObjects.click();
    debugLog.actions.push({ step: "choose-multiple-objects" });
    result.screenshots.push(await captureEvidence(page, evidenceDir, "03-multiple-objects"));

    await waitForAnyVisible(page, selectors.uploadModal, 10000);
    debugLog.actions.push({ step: "upload-modal-open" });

    const maybeNameInput = await firstExisting(page, selectors.nameInput).catch(() => null);
    if (maybeNameInput) {
      await maybeNameInput.fill(run.networkLocationName);
      debugLog.actions.push({ step: "fill-name", value: run.networkLocationName });
    }

    await setFileOnModal(page, selectors, run.storedFilePath, debugLog);

    const maybeUploadButton = await firstVisible(page, selectors.uploadButton, 6000).catch(() => null);
    if (maybeUploadButton) {
      await maybeUploadButton.click();
      debugLog.actions.push({ step: "click-upload" });
    }

    const maybeSaveButton = await firstVisible(page, selectors.saveButton, 4000).catch(() => null);
    if (maybeSaveButton) {
      await maybeSaveButton.click();
      debugLog.actions.push({ step: "click-save" });
    }

    const successLocator = await firstExisting(page, selectors.successSignal).catch(() => null);
    if (successLocator) {
      await successLocator.waitFor({ state: "visible", timeout: 15000 }).catch(() => null);
    } else {
      await page.waitForLoadState("networkidle", { timeout: 15000 }).catch(() => null);
    }

    result.screenshots.push(await captureEvidence(page, evidenceDir, "04-result"));
    result.status = "success";
    result.message = `Network Location ${run.networkLocationName} cargada correctamente en Netskope.`;
    debugLog.actions.push({ step: "completed" });
  } catch (error) {
    result.message = sanitizeError(error);
    result.screenshots.push(await captureEvidence(page, evidenceDir, "error-state").catch(() => null));
    debugLog.actions.push({
      step: "error",
      message: result.message,
      url: safePageUrl(page),
      snapshot: await getPageDebugSnapshot(page)
    });
  } finally {
    await fs.writeFile(result.logsPath, JSON.stringify(debugLog, null, 2), "utf8");
    await context.close();
    await browser.close();
  }

  return result;
}
