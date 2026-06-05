import { runNetskopeInventoryExtraction } from "./src/services/netskopeAutomation.js";

async function readStdin() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks).toString("utf8");
}

try {
  const raw = await readStdin();
  const payload = JSON.parse(raw || "{}");
  const result = await runNetskopeInventoryExtraction({
    id: payload.id
  });

  process.stdout.write(JSON.stringify(result));
} catch (error) {
  process.stdout.write(
    JSON.stringify({
      status: "failed",
      message: error instanceof Error ? error.message : String(error),
      screenshots: [],
      logsPath: null,
      responsePath: null
    })
  );
  process.exitCode = 1;
}
