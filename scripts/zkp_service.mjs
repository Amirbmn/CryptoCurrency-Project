import { createInterface } from "node:readline";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import * as snarkjs from "snarkjs";
import { buildPoseidon } from "circomlibjs";

const root = resolve(import.meta.dirname, "..");
const wasmPath = process.env.ZKP_WASM || resolve(root, "artifacts/zkp/readiness_js/readiness.wasm");
const zkeyPath = process.env.ZKP_ZKEY || resolve(root, "artifacts/zkp/readiness_final.zkey");
const vkeyPath = process.env.ZKP_VKEY || resolve(root, "artifacts/zkp/verification_key.json");

const verificationKey = JSON.parse(await readFile(vkeyPath, "utf8"));
const poseidon = await buildPoseidon();
const field = poseidon.F;

function poseidonDecimal(values) {
  return field.toObject(poseidon(values.map((value) => BigInt(value)))).toString();
}

function sameSignals(actual, expected) {
  if (!Array.isArray(actual) || !Array.isArray(expected) || actual.length !== expected.length) return false;
  return actual.every((value, index) => BigInt(value).toString() === BigInt(expected[index]).toString());
}

async function handle(message) {
  if (message.op === "identity") {
    return {
      identityCommitment: poseidonDecimal([message.identitySecret]),
      nullifier: poseidonDecimal([message.identitySecret, message.sessionId]),
    };
  }

  if (message.op === "prove") {
    const started = process.hrtime.bigint();
    const result = await snarkjs.groth16.fullProve(message.input, wasmPath, zkeyPath);
    const proofMs = Number(process.hrtime.bigint() - started) / 1e6;
    return { proof: result.proof, publicSignals: result.publicSignals, proofMs };
  }

  if (message.op === "verify") {
    const started = process.hrtime.bigint();
    let valid = false;
    try {
      valid = sameSignals(message.publicSignals, message.expectedPublicSignals)
        && await snarkjs.groth16.verify(verificationKey, message.publicSignals, message.proof);
    } catch {
      valid = false;
    }
    const verifyMs = Number(process.hrtime.bigint() - started) / 1e6;
    return { valid, verifyMs };
  }

  if (message.op === "health") return { ready: true };
  throw new Error(`unknown operation: ${message.op}`);
}

const reader = createInterface({ input: process.stdin, crlfDelay: Infinity });
for await (const line of reader) {
  if (!line.trim()) continue;
  let response;
  try {
    const message = JSON.parse(line);
    response = { id: message.id, ok: true, result: await handle(message) };
  } catch (error) {
    response = { ok: false, error: error instanceof Error ? error.message : String(error) };
  }
  process.stdout.write(`${JSON.stringify(response)}\n`);
}
process.exit(0);
