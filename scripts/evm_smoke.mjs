import { resolve } from "node:path";
import ganache from "ganache";
import { ContractFactory, BrowserProvider, randomBytes, hexlify } from "ethers";
import { compileContract } from "./contract_utils.mjs";

const root = resolve(import.meta.dirname, "..");
const { abi, bytecode } = compileContract(root);
const rpc = ganache.provider({ logging: { quiet: true }, wallet: { deterministic: true, totalAccounts: 30 } });
const provider = new BrowserProvider(rpc);
const signers = await provider.listAccounts();
const factory = new ContractFactory(abi, bytecode, signers[0]);
const contract = await factory.deploy();
await contract.waitForDeployment();

const selected = await Promise.all(signers.slice(1, 21).map((signer) => signer.getAddress()));
const startReceipt = await (await contract.startSession(1, selected, "bafyPreviousModel")).wait();
const responseReceipt = await (await contract.connect(signers[1]).submitResponse(1, hexlify(randomBytes(65)))).wait();
const closeReceipt = await (await contract.closeSession(1, "bafyNewModel", "bafySessionLog")).wait();
const session = await contract.getSession(1);

if (Number(session.status) !== 2) throw new Error("session did not close");
console.log(JSON.stringify({
  deployed: await contract.getAddress(),
  startGas: Number(startReceipt.gasUsed),
  submitGas: Number(responseReceipt.gasUsed),
  closeGas: Number(closeReceipt.gasUsed),
  status: Number(session.status),
}, null, 2));

