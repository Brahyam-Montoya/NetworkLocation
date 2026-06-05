import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");

function parseBoolean(value, fallback = false) {
  if (value === undefined || value === null || value === "") {
    return fallback;
  }

  return ["1", "true", "yes", "on"].includes(String(value).toLowerCase());
}

function parseJson(value, fallback) {
  if (!value) {
    return fallback;
  }

  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

export const config = {
  port: Number(process.env.PORT || 3000),
  projectRoot,
  storageDir: projectRoot,
  uploadsDir: path.join(projectRoot, "uploads"),
  logsDir: path.join(projectRoot, "logs", "evidence"),
  historyFile: path.join(projectRoot, "logs", "execution_logs.json"),
  netskope: {
    baseUrl: process.env.NETSKOPE_BASE_URL || "https://gammaingenieros-co.goskope.com",
    user: process.env.NETSKOPE_USER || "",
    password: process.env.NETSKOPE_PASSWORD || "",
    loginPath: process.env.NETSKOPE_LOGIN_PATH || "/",
    networkLocationPath:
      !process.env.NETSKOPE_NETWORK_LOCATION_PATH || process.env.NETSKOPE_NETWORK_LOCATION_PATH === "/ns"
        ? "/ns#/profile-network-location"
        : process.env.NETSKOPE_NETWORK_LOCATION_PATH,
    headless: parseBoolean(process.env.NETSKOPE_HEADLESS, false),
    queryHeadless: parseBoolean(
      process.env.NETSKOPE_QUERY_HEADLESS,
      parseBoolean(process.env.NETSKOPE_HEADLESS, false)
    ),
    selectorsOverride: parseJson(process.env.NETSKOPE_SELECTORS_JSON, {})
  }
};
