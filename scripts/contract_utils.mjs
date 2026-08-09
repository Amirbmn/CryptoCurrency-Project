import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import solc from "solc";

export function compileContract(root) {
  const sourcePath = resolve(root, "contracts/HybridAttendance.sol");
  const input = {
    language: "Solidity",
    sources: {
      "HybridAttendance.sol": { content: readFileSync(sourcePath, "utf8") },
    },
    settings: {
      optimizer: { enabled: true, runs: 200 },
      evmVersion: "shanghai",
      outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } },
    },
  };
  const output = JSON.parse(solc.compile(JSON.stringify(input)));
  const errors = (output.errors || []).filter((item) => item.severity === "error");
  if (errors.length) throw new Error(errors.map((item) => item.formattedMessage).join("\n"));
  const artifact = output.contracts["HybridAttendance.sol"].HybridAttendance;
  return { abi: artifact.abi, bytecode: `0x${artifact.evm.bytecode.object}` };
}
