import { config } from "../config.js";
import { ensureDir, readJsonFile, writeJsonFile } from "../utils/fs.js";

async function loadHistory() {
  await ensureDir(config.storageDir);
  const items = await readJsonFile(config.historyFile, []);
  return Array.isArray(items) ? items : [];
}

export async function listHistory() {
  const items = await loadHistory();
  return items.sort((left, right) => right.createdAt.localeCompare(left.createdAt));
}

export async function saveRun(entry) {
  const items = await loadHistory();
  items.push(entry);
  await writeJsonFile(config.historyFile, items);
  return entry;
}

export async function updateRun(runId, patch) {
  const items = await loadHistory();
  const index = items.findIndex((item) => item.id === runId);

  if (index === -1) {
    throw new Error(`Run ${runId} not found`);
  }

  items[index] = { ...items[index], ...patch };
  await writeJsonFile(config.historyFile, items);
  return items[index];
}

export async function getRun(runId) {
  const items = await loadHistory();
  return items.find((item) => item.id === runId) || null;
}
