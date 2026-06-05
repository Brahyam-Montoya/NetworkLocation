import fs from "node:fs/promises";
import path from "node:path";
import fsSync from "node:fs";
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
  applyChangesButton: [
    "button:has-text('APPLY CHANGES')",
    "button:has-text('Apply Changes')",
    "text=APPLY CHANGES",
    "text=Apply Changes"
  ],
  applyChangesModal: [
    "[role='dialog']",
    ".modal-content",
    ".ns-modal-content",
    "textarea"
  ],
  sendForApprovalTitle: [
    "text=Send For Approval",
    "text=Send for approval"
  ],
  approvalRecipientInput: [
    "[role='dialog'] input[type='text']",
    ".modal-content input[type='text']",
    ".ns-modal-content input[type='text']",
    "[role='dialog'] input:not([type])",
    ".modal-content input:not([type])",
    ".ns-modal-content input:not([type])"
  ],
  applyChangesCommentInput: [
    "[role='dialog'] textarea",
    ".modal-content textarea",
    ".ns-modal-content textarea",
    "[role='dialog'] [contenteditable='true']",
    ".modal-content [contenteditable='true']",
    ".ns-modal-content [contenteditable='true']",
    "textarea"
  ],
  applyChangesConfirmButton: [
    "[role='dialog'] button:has-text('APPLY CHANGES')",
    ".modal-content button:has-text('APPLY CHANGES')",
    ".ns-modal-content button:has-text('APPLY CHANGES')",
    "[role='dialog'] button:has-text('Apply Changes')",
    ".modal-content button:has-text('Apply Changes')",
    ".ns-modal-content button:has-text('Apply Changes')",
    "[role='dialog'] button:has-text('APPLY')",
    ".modal-content button:has-text('APPLY')",
    ".ns-modal-content button:has-text('APPLY')",
    "[role='dialog'] button:has-text('Apply')",
    ".modal-content button:has-text('Apply')",
    ".ns-modal-content button:has-text('Apply')"
  ],
  approvalSendButton: [
    "[role='dialog'] button:has-text('SEND')",
    ".modal-content button:has-text('SEND')",
    ".ns-modal-content button:has-text('SEND')",
    "[role='dialog'] button:has-text('Send')",
    ".modal-content button:has-text('Send')",
    ".ns-modal-content button:has-text('Send')"
  ],
  applyChangesSuccessSignal: [
    "text=Changes applied",
    "text=Request sent",
    "text=Approval request sent",
    "text=successfully",
    "text=Pending changes",
    ".toast-success"
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

async function waitUntilEnabled(locator, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const visible = await locator.isVisible().catch(() => false);
    const enabled = await locator.isEnabled().catch(() => false);

    if (visible && enabled) {
      return locator;
    }

    await new Promise((resolve) => setTimeout(resolve, 250));
  }

  return locator;
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

function resolveApprovalRecipient(run) {
  const candidate = (
    run?.approvalRecipient ||
    process.env.NETWORK_LOCATION_NOTIFY_EMAIL ||
    "brahyam.montoya@gammaingenieros.com"
  ).trim();

  return candidate.toLowerCase();
}

function safePageUrl(page) {
  try {
    return page.url();
  } catch {
    return "";
  }
}

async function launchBrowser(headless) {
  const candidates = [
    { channel: "chrome", headless },
    {
      executablePath: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      headless
    },
    {
      executablePath: "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
      headless
    },
    {
      executablePath: path.join(process.env.LOCALAPPDATA || "", "Google\\Chrome\\Application\\chrome.exe"),
      headless
    },
    {
      executablePath: "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
      headless
    },
    {
      executablePath: "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
      headless
    },
    { headless }
  ];

  let lastError;

  for (const candidate of candidates) {
    if (candidate.executablePath && !fsSync.existsSync(candidate.executablePath)) {
      continue;
    }

    try {
      return await chromium.launch(candidate);
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError;
}

async function createBrowserContext(browser) {
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

  return context;
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
      inputCount: document.querySelectorAll("input").length,
      visibleButtons: Array.from(document.querySelectorAll("button, [role='button'], a"))
        .filter((element) => {
          const style = window.getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
        })
        .map((element) => (element.innerText || element.textContent || "").trim())
        .filter(Boolean)
        .slice(0, 20)
    }));
  } catch {
    return {
      title: "",
      url: safePageUrl(page),
      bodyText: "",
      inputCount: 0,
      visibleButtons: []
    };
  }
}

async function findApplyConfirmButton(page, selectors, modalRoot = null) {
  const scopedRoot = modalRoot || page;
  const roleCandidates = [
    scopedRoot.getByRole("button", { name: /^apply$/i }),
    scopedRoot.getByRole("button", { name: /^apply changes$/i }),
    scopedRoot.getByRole("button", { name: /apply/i })
  ];

  for (const locator of roleCandidates) {
    const count = await locator.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const candidate = locator.nth(index);
      if (await candidate.isVisible().catch(() => false)) {
        return candidate;
      }
    }
  }

  return firstVisible(scopedRoot, selectors.applyChangesConfirmButton, 6000);
}

async function findApprovalSendButton(page, selectors, modalRoot = null) {
  const scopedRoot = modalRoot || page;
  const roleCandidates = [
    scopedRoot.getByRole("button", { name: /^send$/i }),
    scopedRoot.getByRole("button", { name: /send/i })
  ];

  for (const locator of roleCandidates) {
    const count = await locator.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const candidate = locator.nth(index);
      if (await candidate.isVisible().catch(() => false)) {
        return candidate;
      }
    }
  }

  return firstVisible(scopedRoot, selectors.approvalSendButton, 6000);
}

async function applyPendingChanges(page, selectors, run, debugLog, evidenceDir, result) {
  if (!run.applyChangeMessage) {
    throw new Error("No se recibio el comentario requerido para Apply changes.");
  }

  const approvalRecipient = resolveApprovalRecipient(run);

  const applyChangesButton = await waitForAnyVisible(page, selectors.applyChangesButton, 20000);
  await applyChangesButton.click();
  debugLog.actions.push({ step: "open-apply-changes" });

  await waitForAnyVisible(page, selectors.applyChangesModal, 10000);
  const commentInput = await firstVisible(page, selectors.applyChangesCommentInput, 6000);
  await commentInput.fill(run.applyChangeMessage);
  debugLog.actions.push({ step: "fill-apply-comment", value: run.applyChangeMessage });

  const modalRootCandidate = page.locator("[role='dialog'], .modal-content, .ns-modal-content").filter({ has: commentInput }).first();
  const modalRoot = (await modalRootCandidate.count().catch(() => 0)) > 0 ? modalRootCandidate : page;
  const approvalTitleVisible = await waitForAnyVisible(page, selectors.sendForApprovalTitle, 1500).catch(() => null);
  const approvalRecipientInput = await firstVisible(page, selectors.approvalRecipientInput, 1500).catch(() => null);

  if (approvalTitleVisible || approvalRecipientInput) {
    if (!approvalRecipient) {
      throw new Error("No se configuro approvalRecipient para Send For Approval.");
    }

    if (approvalRecipientInput) {
      await approvalRecipientInput.fill(approvalRecipient);
      debugLog.actions.push({ step: "fill-approval-recipient", value: approvalRecipient });
    }

    const approvalConfirmButton = await findApplyConfirmButton(page, selectors, modalRoot).catch(() => null);

    if (approvalConfirmButton) {
      await waitUntilEnabled(approvalConfirmButton, 10000);
      await Promise.all([
        page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => null),
        approvalConfirmButton.click({ force: true })
      ]);
      debugLog.actions.push({ step: "apply-after-approval", url: safePageUrl(page) });
    } else {
      const sendButton = await findApprovalSendButton(page, selectors, modalRoot);
      await waitUntilEnabled(sendButton, 10000);
      await Promise.all([
        page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => null),
        sendButton.click({ force: true })
      ]);
      debugLog.actions.push({ step: "send-for-approval", url: safePageUrl(page) });
    }

    const postApprovalApplyButton = await waitForAnyVisible(page, selectors.applyChangesButton, 4000).catch(() => null);
    if (postApprovalApplyButton) {
      await postApprovalApplyButton.click().catch(() => null);
      debugLog.actions.push({ step: "reopen-apply-after-approval" });

      const secondConfirmButton = await findApplyConfirmButton(page, selectors).catch(() => null);
      if (secondConfirmButton) {
        await waitUntilEnabled(secondConfirmButton, 10000);
        await Promise.all([
          page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => null),
          secondConfirmButton.click({ force: true })
        ]);
        debugLog.actions.push({ step: "final-apply-after-approval", url: safePageUrl(page) });
      }
    }
  } else {
    const confirmApplyButton = await findApplyConfirmButton(page, selectors, modalRoot);
    await waitUntilEnabled(confirmApplyButton, 10000);
    await Promise.all([
      page.waitForLoadState("networkidle", { timeout: 20000 }).catch(() => null),
      confirmApplyButton.click({ force: true })
    ]);
    debugLog.actions.push({ step: "confirm-apply-changes", url: safePageUrl(page) });
  }

  const appliedSignal = await firstExisting(page, selectors.applyChangesSuccessSignal).catch(() => null);
  if (appliedSignal) {
    await appliedSignal.waitFor({ state: "visible", timeout: 15000 }).catch(() => null);
  } else {
    await page.waitForTimeout(2500);
  }

  result.screenshots.push(await captureEvidence(page, evidenceDir, "05-apply-changes"));
}

function isInventoryResponse(response) {
  const url = response.url();
  return (
    url.includes("readAllNetLocationObjs") &&
    ["xhr", "fetch"].includes(response.request().resourceType())
  );
}

export async function runNetskopeAutomation(run) {
  const selectors = mergedSelectors();
  const evidenceDir = path.join(config.logsDir, run.id);
  await ensureDir(evidenceDir);

  if (!config.netskope.user || !config.netskope.password) {
    throw new Error("Faltan NETSKOPE_USER o NETSKOPE_PASSWORD en el archivo .env");
  }

  let browser;
  let context;
  let page;

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
    browser = await launchBrowser(config.netskope.headless);
    context = await createBrowserContext(browser);
    page = await context.newPage();
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
    await applyPendingChanges(page, selectors, run, debugLog, evidenceDir, result);
    result.status = "success";
    result.message = `Network Location ${run.networkLocationName} cargada correctamente en Netskope.`;
    result.appliedChangeMessage = run.applyChangeMessage;
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
    if (context) {
      await context.close();
    }
    if (browser) {
      await browser.close();
    }
  }

  return result;
}

export async function runNetskopeInventoryExtraction(run) {
  const selectors = mergedSelectors();
  const evidenceDir = path.join(config.logsDir, run.id);
  await ensureDir(evidenceDir);
  await ensureDir(config.uploadsDir);

  if (!config.netskope.user || !config.netskope.password) {
    throw new Error("Faltan NETSKOPE_USER o NETSKOPE_PASSWORD en el archivo .env");
  }

  let browser;
  let context;
  let page;

  const result = {
    status: "failed",
    message: "",
    screenshots: [],
    logsPath: path.join(evidenceDir, "inventory-automation-log.json"),
    responsePath: null
  };

  const debugLog = {
    runId: run.id,
    loginUrl: resolvePortalUrl(config.netskope.baseUrl, config.netskope.loginPath),
    networkLocationUrl: resolvePortalUrl(config.netskope.baseUrl, config.netskope.networkLocationPath),
    headless: config.netskope.queryHeadless,
    actions: []
  };

  try {
    browser = await launchBrowser(config.netskope.queryHeadless);
    context = await createBrowserContext(browser);
    page = await context.newPage();

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
    const inventoryResponsePromise = page.waitForResponse(isInventoryResponse, { timeout: 30000 });
    await navigateThroughPoliciesMenu(page, selectors, debugLog);
    result.screenshots.push(await captureEvidence(page, evidenceDir, "02-network-location"));

    const inventoryResponse = await inventoryResponsePromise;
    const responseText = (await inventoryResponse.text()).trim();
    if (!responseText) {
      throw new Error("Netskope no devolvio contenido en readAllNetLocationObjs.");
    }

    const responseFilePath = path.join(config.uploadsDir, `${run.id}-readAllNetLocationObjs.json`);
    await fs.writeFile(responseFilePath, responseText, "utf8");
    result.responsePath = responseFilePath;
    debugLog.actions.push({
      step: "capture-readAllNetLocationObjs",
      url: inventoryResponse.url(),
      status: inventoryResponse.status(),
      responsePath: responseFilePath
    });

    result.screenshots.push(await captureEvidence(page, evidenceDir, "03-readAllNetLocationObjs"));
    result.status = "success";
    result.message = "Respuesta readAllNetLocationObjs capturada correctamente desde Netskope.";
    debugLog.actions.push({ step: "completed" });
  } catch (error) {
    result.message = sanitizeError(error);
    result.screenshots.push(await captureEvidence(page, evidenceDir, "error-state").catch(() => null));
    debugLog.actions.push({
      step: "error",
      message: result.message,
      url: safePageUrl(page),
      snapshot: page ? await getPageDebugSnapshot(page) : null
    });
  } finally {
    await fs.writeFile(result.logsPath, JSON.stringify(debugLog, null, 2), "utf8");
    if (context) {
      await context.close();
    }
    if (browser) {
      await browser.close();
    }
  }

  return result;
}
