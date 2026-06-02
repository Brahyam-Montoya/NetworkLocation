import express from "express";
import path from "node:path";
import { config } from "./config.js";
import { ensureDir } from "./utils/fs.js";
import { buildRunDraft, uploadMiddleware } from "./services/uploadService.js";
import { getRun, listHistory, saveRun, updateRun } from "./services/historyStore.js";
import { runNetskopeAutomation } from "./services/netskopeAutomation.js";
import { enqueueAutomation } from "./services/jobQueue.js";

const app = express();

app.use(express.urlencoded({ extended: false }));
app.use("/static", express.static(path.join(config.projectRoot, "src", "public")));
app.use("/storage", express.static(config.storageDir));

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("\"", "&quot;")
    .replaceAll("'", "&#39;");
}

function renderPage({ flashMessage = "", flashType = "info", history = [] }) {
  const rows = history.map((item) => {
    const evidencePath = item.logsPath ? path.relative(config.projectRoot, item.logsPath) : "";
    const evidenceHref = item.logsPath ? `/${path.relative(config.projectRoot, item.logsPath).replaceAll("\\", "/")}` : "";
    return `
      <tr>
        <td>${escapeHtml(item.createdAt)}</td>
        <td>${escapeHtml(item.networkLocationName || "-")}</td>
        <td>${escapeHtml(item.originalFileName || "-")}</td>
        <td><span class="status ${escapeHtml(item.status)}">${escapeHtml(item.status)}</span></td>
        <td>${escapeHtml(item.message || "-")}</td>
        <td>${escapeHtml(item.storedFilePath || "-")}</td>
        <td>${evidenceHref ? `<a href="${escapeHtml(evidenceHref)}" target="_blank" rel="noreferrer">${escapeHtml(evidencePath)}</a>` : "-"}</td>
        <td>
          <form action="/runs/${escapeHtml(item.id)}/retry-page" method="post">
            <button class="retry-button" type="submit">Reintentar</button>
          </form>
        </td>
      </tr>
    `;
  }).join("");

  return `<!DOCTYPE html>
  <html lang="es">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>Network Location</title>
      <link rel="stylesheet" href="/static/styles.css" />
    </head>
    <body>
      <main class="page">
        <section class="hero">
          <p class="eyebrow">Local Automation</p>
          <h1>Network Location</h1>
          <p class="lede">Sube un CSV, guardalo localmente y ejecuta el flujo de Netskope para crear la Network Location en modo Multiple Objects.</p>
        </section>

        <section class="panel">
          ${flashMessage ? `<div class="flash ${escapeHtml(flashType)}">${escapeHtml(flashMessage)}</div>` : ""}
          <form class="upload-form" action="/upload" method="post" enctype="multipart/form-data">
            <label for="file">Archivo CSV</label>
            <input id="file" name="file" type="file" accept=".csv,text/csv" required />
            <button type="submit">Subir y ejecutar</button>
          </form>
        </section>

        <section class="panel">
          <div class="section-heading">
            <h2>Historial</h2>
            <p>Ultimas ejecuciones guardadas localmente.</p>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Network Location</th>
                  <th>Archivo</th>
                  <th>Estado</th>
                  <th>Mensaje</th>
                  <th>Ruta</th>
                  <th>Log</th>
                  <th>Accion</th>
                </tr>
              </thead>
              <tbody>
                ${rows || `<tr><td colspan="8" class="empty">Todavia no hay ejecuciones.</td></tr>`}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </body>
  </html>`;
}

app.get("/", async (_req, res, next) => {
  try {
    const history = await listHistory();
    res.type("html").send(renderPage({ history }));
  } catch (error) {
    next(error);
  }
});

app.post("/upload", (req, res, next) => {
  uploadMiddleware(req, res, (error) => {
    if (error) {
      next(error);
      return;
    }

    next();
  });
}, async (req, res, next) => {
  try {
    const runDraft = await buildRunDraft(req.file);
    await saveRun(runDraft);

    const startedAt = new Date().toISOString();
    await updateRun(runDraft.id, {
      status: "running",
      startedAt,
      message: "Automatizacion en progreso."
    });

    const execution = await enqueueAutomation(() => runNetskopeAutomation({ ...runDraft, startedAt }));
    await updateRun(runDraft.id, {
      status: execution.status,
      message: execution.message,
      startedAt,
      finishedAt: new Date().toISOString(),
      screenshots: execution.screenshots,
      logsPath: execution.logsPath
    });

    const history = await listHistory();
    res.status(execution.status === "success" ? 200 : 500).type("html").send(renderPage({
      history,
      flashMessage: execution.message,
      flashType: execution.status === "success" ? "success" : "error"
    }));
  } catch (error) {
    next(error);
  }
});

app.post("/runs/:id/retry", async (req, res, next) => {
  try {
    const run = await getRun(req.params.id);

    if (!run) {
      res.status(404).json({ message: "Run no encontrado." });
      return;
    }

    const startedAt = new Date().toISOString();
    await updateRun(run.id, {
      status: "running",
      startedAt,
      finishedAt: null,
      message: "Reintentando automatizacion."
    });

    const execution = await enqueueAutomation(() => runNetskopeAutomation({ ...run, startedAt }));
    const updatedRun = await updateRun(run.id, {
      status: execution.status,
      message: execution.message,
      startedAt,
      finishedAt: new Date().toISOString(),
      screenshots: execution.screenshots,
      logsPath: execution.logsPath
    });

    res.json(updatedRun);
  } catch (error) {
    next(error);
  }
});

app.post("/runs/:id/retry-page", async (req, res, next) => {
  try {
    const run = await getRun(req.params.id);

    if (!run) {
      throw new Error("Run no encontrado.");
    }

    const startedAt = new Date().toISOString();
    await updateRun(run.id, {
      status: "running",
      startedAt,
      finishedAt: null,
      message: "Reintentando automatizacion."
    });

    const execution = await enqueueAutomation(() => runNetskopeAutomation({ ...run, startedAt }));
    await updateRun(run.id, {
      status: execution.status,
      message: execution.message,
      startedAt,
      finishedAt: new Date().toISOString(),
      screenshots: execution.screenshots,
      logsPath: execution.logsPath
    });

    const history = await listHistory();
    res.status(execution.status === "success" ? 200 : 500).type("html").send(renderPage({
      history,
      flashMessage: execution.message,
      flashType: execution.status === "success" ? "success" : "error"
    }));
  } catch (error) {
    next(error);
  }
});

app.use(async (error, _req, res, _next) => {
  await ensureDir(config.storageDir);
  const history = await listHistory().catch(() => []);
  res.status(500).type("html").send(renderPage({
    history,
    flashMessage: error.message || "Ocurrio un error inesperado.",
    flashType: "error"
  }));
});

export default app;
