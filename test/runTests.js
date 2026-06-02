import assert from "node:assert/strict";
import { extractNetworkLocationName } from "../src/services/csvService.js";

function run(name, fn) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

run("extracts the first CSV value as the network location name", () => {
  const value = extractNetworkLocationName("CO_AzureArc_Server,10.0.0.1,10.0.0.2");
  assert.equal(value, "CO_AzureArc_Server");
});

run("rejects empty CSV content", () => {
  assert.throws(
    () => extractNetworkLocationName(""),
    /CSV esta vacio/
  );
});

run("rejects a first row without a first value", () => {
  assert.throws(
    () => extractNetworkLocationName(",10.0.0.1"),
    /No fue posible detectar/
  );
});

console.log("All tests passed.");
