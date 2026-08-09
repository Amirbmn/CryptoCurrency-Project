import { spawn } from "node:child_process";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const service = spawn(process.execPath, [resolve(root, "scripts/zkp_service.mjs")], {
  cwd: root,
  stdio: ["pipe", "pipe", "inherit"],
});

let nextId = 1;
const pending = new Map();
let buffer = "";
service.stdout.setEncoding("utf8");
service.stdout.on("data", (chunk) => {
  buffer += chunk;
  while (buffer.includes("\n")) {
    const index = buffer.indexOf("\n");
    const line = buffer.slice(0, index);
    buffer = buffer.slice(index + 1);
    if (!line) continue;
    const message = JSON.parse(line);
    const waiter = pending.get(message.id);
    if (waiter) {
      pending.delete(message.id);
      message.ok ? waiter.resolve(message.result) : waiter.reject(new Error(message.error));
    }
  }
});

function call(op, payload = {}) {
  const id = nextId++;
  return new Promise((resolvePromise, reject) => {
    pending.set(id, { resolve: resolvePromise, reject });
    service.stdin.write(`${JSON.stringify({ id, op, ...payload })}\n`);
  });
}

const identitySecret = "123456789";
const sessionId = 1;
const identity = await call("identity", { identitySecret, sessionId });
const input = {
  E: 820,
  Q: 780,
  D: 800,
  identitySecret,
  shatE: 750,
  shatQ: 750,
  shatD: 750,
  alphaE: 400,
  alphaQ: 300,
  alphaD: 300,
  errorBound: 300000000,
  sessionId,
  identityCommitment: identity.identityCommitment,
  nullifier: identity.nullifier,
};
const proved = await call("prove", { input });
const verified = await call("verify", {
  proof: proved.proof,
  publicSignals: proved.publicSignals,
  expectedPublicSignals: proved.publicSignals,
});
if (!verified.valid) throw new Error("valid readiness proof was rejected");

const tampered = [...proved.publicSignals];
tampered[1] = (BigInt(tampered[1]) + 1n).toString();
const rejected = await call("verify", {
  proof: proved.proof,
  publicSignals: tampered,
  expectedPublicSignals: tampered,
});
if (rejected.valid) throw new Error("tampered readiness proof was accepted");

console.log(JSON.stringify({
  validProof: verified.valid,
  tamperedProofRejected: !rejected.valid,
  proofMs: proved.proofMs,
  verifyMs: verified.verifyMs,
  publicSignalCount: proved.publicSignals.length,
}, null, 2));
service.stdin.end();
await new Promise((resolvePromise) => service.once("close", resolvePromise));
