import { config } from "./config.js";
import { ensureDir } from "./utils/fs.js";
import app from "./app.js";
import { recoverInterruptedRuns } from "./services/runRecovery.js";

async function bootstrap() {
  await ensureDir(config.storageDir);
  await ensureDir(config.uploadsDir);
  await ensureDir(config.logsDir);
  await recoverInterruptedRuns();

  app.listen(config.port, () => {
    console.log(`Network Location disponible en http://localhost:${config.port}`);
  });
}

bootstrap().catch((error) => {
  console.error("No fue posible iniciar la aplicacion.", error);
  process.exitCode = 1;
});
