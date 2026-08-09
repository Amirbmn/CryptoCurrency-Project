import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import ganache from "ganache";
import { ContractFactory, BrowserProvider, randomBytes, hexlify } from "ethers";
import { compileContract } from "./contract_utils.mjs";

const root = resolve(import.meta.dirname, "..");
const inputPath = resolve(root, process.argv[2] || "output/evm_plan.json");
const outputPath = resolve(root, process.argv[3] || "output/evm_gas_results.json");
const plan = JSON.parse(readFileSync(inputPath, "utf8"));
const { abi, bytecode } = compileContract(root);
const allResults = {};

for (const [scenario, sessions] of Object.entries(plan)) {
  const rpc = ganache.provider({
    logging: { quiet: true },
    wallet: { deterministic: true, totalAccounts: 110 },
    chain: { hardfork: "shanghai" },
  });
  const provider = new BrowserProvider(rpc);
  const signers = await provider.listAccounts();
  const contract = await new ContractFactory(abi, bytecode, signers[0]).deploy();
  await contract.waitForDeployment();
  const scenarioResults = [];

  for (const item of sessions) {
    const selectedSigners = signers.slice(1, 1 + item.selected_count);
    const selectedAddresses = await Promise.all(selectedSigners.map((signer) => signer.getAddress()));
    const startReceipt = await (
      await contract.startSession(item.session_id, selectedAddresses, item.previous_model_cid)
    ).wait();

    const submitGas = [];
    for (let index = 0; index < item.response_count; index++) {
      const signature = hexlify(randomBytes(65));
      const receipt = await (
        await contract.connect(selectedSigners[index]).submitResponse(item.session_id, signature)
      ).wait();
      submitGas.push(Number(receipt.gasUsed));
    }

    const closeReceipt = await (
      await contract.closeSession(item.session_id, item.model_cid, item.log_cid)
    ).wait();
    const startGas = Number(startReceipt.gasUsed);
    const submitGasTotal = submitGas.reduce((sum, value) => sum + value, 0);
    const closeGas = Number(closeReceipt.gasUsed);
    scenarioResults.push({
      session_id: item.session_id,
      start_gas: startGas,
      submit_gas: submitGasTotal,
      close_gas: closeGas,
      total_gas: startGas + submitGasTotal + closeGas,
      response_count: item.response_count,
    });
  }
  allResults[scenario] = scenarioResults;
}

writeFileSync(outputPath, `${JSON.stringify(allResults, null, 2)}\n`);
console.log(`Wrote EVM receipt gas measurements to ${outputPath}`);

