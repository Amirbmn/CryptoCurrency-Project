import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(import.meta.dirname, "..");
const out = resolve(root, "artifacts/zkp");
mkdirSync(out, { recursive: true });

const circom = resolve(root, "node_modules/.bin/circom2");
const snarkjs = resolve(root, "node_modules/.bin/snarkjs");
const circuit = resolve(root, "circuits/readiness.circom");
const wasm = resolve(out, "readiness_js/readiness.wasm");
const r1cs = resolve(out, "readiness.r1cs");
const finalZkey = resolve(out, "readiness_final.zkey");
const verificationKey = resolve(out, "verification_key.json");

function run(binary, args) {
  const result = spawnSync(binary, args, { cwd: root, stdio: "inherit" });
  if (result.status !== 0) {
    throw new Error(`${binary} failed with exit code ${result.status}`);
  }
}

const force = process.env.ZKP_FORCE === "1";
if (!force && existsSync(wasm) && existsSync(r1cs) && existsSync(finalZkey) && existsSync(verificationKey)) {
  console.log("ZKP artifacts already exist; setup is complete.");
  process.exit(0);
}

run(circom, [circuit, "--r1cs", "--wasm", "--sym", "--O2", "-o", out]);
writeFileSync(resolve(out, "readiness_js/package.json"), '{"type":"commonjs"}\n');

const pot0 = resolve(out, "pot12_0000.ptau");
const pot1 = resolve(out, "pot12_0001.ptau");
const potFinal = resolve(out, "pot12_final.ptau");

run(snarkjs, ["powersoftau", "new", "bn128", "12", pot0]);
run(snarkjs, [
  "powersoftau",
  "contribute",
  pot0,
  pot1,
  "--name=local course-project contribution",
  `-e=${randomBytes(32).toString("hex")}`,
]);
run(snarkjs, ["powersoftau", "prepare", "phase2", pot1, potFinal]);
run(snarkjs, ["groth16", "setup", r1cs, potFinal, finalZkey]);
run(snarkjs, ["zkey", "verify", r1cs, potFinal, finalZkey]);
run(snarkjs, ["zkey", "export", "verificationkey", finalZkey, verificationKey]);

for (const temporary of [pot0, pot1, potFinal]) {
  if (existsSync(temporary)) rmSync(temporary);
}

console.log("Groth16 readiness artifacts generated and verified.");
