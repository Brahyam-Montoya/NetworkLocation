import fs from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";
import multer from "multer";
import { config } from "../config.js";
import { ensureDir } from "../utils/fs.js";
import { extractNetworkLocationName } from "./csvService.js";

function safeBaseName(fileName) {
  return path.basename(fileName).replace(/[^a-zA-Z0-9._-]/g, "_");
}

const storage = multer.diskStorage({
  async destination(_req, _file, callback) {
    try {
      await ensureDir(config.uploadsDir);
      callback(null, config.uploadsDir);
    } catch (error) {
      callback(error);
    }
  },
  filename(_req, file, callback) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
    callback(null, `${timestamp}-${safeBaseName(file.originalname)}`);
  }
});

function fileFilter(_req, file, callback) {
  const extension = path.extname(file.originalname).toLowerCase();

  if (extension !== ".csv") {
    callback(new Error("Solo se permiten archivos .csv"));
    return;
  }

  callback(null, true);
}

export const uploadMiddleware = multer({
  storage,
  fileFilter,
  limits: {
    files: 1,
    fileSize: 10 * 1024 * 1024
  }
}).single("file");

export async function buildRunDraft(file) {
  if (!file) {
    throw new Error("Debes seleccionar un archivo CSV.");
  }

  const csvContent = await fs.readFile(file.path, "utf8");
  const networkLocationName = extractNetworkLocationName(csvContent);
  const now = new Date().toISOString();

  return {
    id: randomUUID(),
    createdAt: now,
    startedAt: null,
    finishedAt: null,
    status: "pending",
    message: "Archivo recibido. Listo para ejecutar.",
    originalFileName: file.originalname,
    storedFileName: path.basename(file.path),
    storedFilePath: file.path,
    networkLocationName
  };
}
