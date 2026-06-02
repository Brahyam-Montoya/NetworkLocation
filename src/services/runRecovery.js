import { config } from "../config.js";
import { readJsonFile, writeJsonFile } from "../utils/fs.js";

export async function recoverInterruptedRuns() {
  const history = await readJsonFile(config.historyFile, []);
  const finishedAt = new Date().toISOString();
  let changed = false;

  for (const item of history) {
    if (item.status !== "running") {
      continue;
    }

    item.status = "failed";
    item.finishedAt = finishedAt;
    item.message = "La ejecucion anterior fue interrumpida antes de completar el registro del resultado.";
    changed = true;
  }

  if (changed) {
    await writeJsonFile(config.historyFile, history);
  }
}
