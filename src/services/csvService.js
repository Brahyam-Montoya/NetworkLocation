import fs from "node:fs/promises";
import path from "node:path";

function normalizeCsvLine(content) {
  return content.replace(/^\uFEFF/, "").split(/\r?\n/)[0]?.trim() || "";
}

export function extractNetworkLocationName(csvContent) {
  const firstLine = normalizeCsvLine(csvContent);

  if (!firstLine) {
    throw new Error("El CSV esta vacio o no tiene contenido legible.");
  }

  const firstValue = firstLine.split(",")[0]?.trim();

  if (!firstValue) {
    throw new Error("No fue posible detectar el nombre de la Network Location en la primera columna.");
  }

  return firstValue;
}

export async function readCsvMetadata(filePath) {
  const csvContent = await fs.readFile(filePath, "utf8");
  const networkLocationName = extractNetworkLocationName(csvContent);

  return {
    csvContent,
    networkLocationName,
    fileName: path.basename(filePath)
  };
}
