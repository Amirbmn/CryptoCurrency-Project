# Hybrid Blockchain Attendance

An experimental attendance system combining **federated learning**, **Groth16 zero-knowledge proofs**, and a **Solidity attendance registry**. The project simulates student readiness and attendance, compares selection strategies, and exports model accuracy, proof timings, and local EVM gas measurements.

The default experiment uses **100 students**, selects up to **20 students per session**, and runs **40 sessions per scenario**. Synthetic data and a configurable random seed make it possible to compare strategies under the same simulated conditions.

See the [project report](report.pdf) (in Persian) for the design and experimental discussion.

## What this project includes

- **Hybrid selection:** rank candidates by predicted attendance and participation history, then combine greedy and random selection. At the default settings, a full selection contains 12 ranked candidates and 8 randomly chosen candidates.
- **Readiness proofs:** a Circom circuit checks a weighted prediction-error threshold while keeping the three state values and identity secret private. Poseidon commitments and session-specific nullifiers bind proofs to an enrolled identity and session.
- **Federated learning:** a NumPy MLP with a 3–8–1 architecture, two local training epochs, and sample-weighted FedAvg updates.
- **Attendance recording:** session challenges, selected wallets, signed responses, and model/log content identifiers.
- **Experiment outputs:** per-session reports, CSV/JSON summaries, comparison plots, proof logs, and gas measured from Ganache transaction receipts.

The experiment itself runs through a Python blockchain emulator. A separate Node.js script replays the session plan against the Solidity contract to measure gas. Model and log storage uses local files with raw CIDv1 identifiers.

## Quick start

### 1. Set up Python

Use Python 3.10 or newer with `pip` and `venv`. The commands below assume Bash on Linux, macOS, or WSL. After extracting the repository, run:

```bash
cd CryptoCurrency-Project-main
python3 -m venv .venv
source .venv/bin/activate
python -m pip install numpy pandas matplotlib PyYAML cryptography
```

Run subsequent commands from the repository root with the virtual environment active. This snapshot does not include a `requirements.txt`, `pyproject.toml`, or root-level `package.json`; the dependencies are installed explicitly here.

### 2. Run a Python-only experiment

```bash
python run_experiments.py --zkp-backend ideal --skip-evm
```

This runs all three scenarios, prints a comparison table, and writes reports and plots under `output/`. The `ideal` backend is a fast testing substitute for cryptographic proofs. With `--skip-evm`, all gas fields are zero. This mode requires no Node.js installation.

**Runs overwrite summaries and matching scenario outputs.** To preserve the bundled results or compare multiple runs, copy `config.yaml` and set both `storage.output_dir` and `storage.ipfs_dir` to new directories before running with `--config`.

### 3. Enable Groth16 proofs and EVM measurements

Install Node.js 22 or newer with npm, then install the Node dependencies from the repository root:

```bash
npm install --no-save --package-lock=false ethers@6 ganache@7 solc@0.8 snarkjs@0.7 circomlibjs@0.1 circomlib@2 circom2@0.2
```

The [npm install options](https://docs.npmjs.com/cli/v11/commands/npm-install/) above install dependencies locally without adding a manifest or lockfile. These version ranges follow the APIs used by the source; the exact dependency versions used for the bundled results are not recorded.

Compiled circuit artifacts and proving/verification keys are already included in `artifacts/zkp/`. Check the two Node workflows, then run the full experiment:

```bash
node scripts/zkp_smoke.mjs
node scripts/evm_smoke.mjs
python run_experiments.py
```

The default configuration uses Groth16, and EVM measurement is enabled unless `--skip-evm` is supplied. Ganache runs locally inside the scripts; no external RPC endpoint, funded wallet, or IPFS daemon is needed. Full proof generation takes longer than the Python-only run.

## Experiment scenarios

| Scenario | Candidate filtering | Selection |
| --- | --- | --- |
| `proposed` | Verify readiness proofs | 60% greedy, 40% random by default |
| `random` | Verify readiness proofs | Uniform random selection |
| `no_zkp` | Accept readiness claims without proof verification | Same hybrid selection as `proposed` |

The greedy score combines the MLP's predicted attendance probability with the student's historical attendance rate. The two components have equal weight by default. If there are fewer valid candidates than the configured selection size, all available candidates are selected.

Run a subset of scenarios:

```bash
python run_experiments.py --scenarios proposed random
```

Run Groth16 proofs without the EVM replay:

```bash
python run_experiments.py --zkp-backend groth16 --skip-evm
```

Run only the scenario without proof verification, using no Node.js components:

```bash
python run_experiments.py --scenarios no_zkp --zkp-backend ideal --skip-evm
```

The explicit `ideal` override matters: the runner initializes the configured proof backend even when `no_zkp` is the only selected scenario.

| CLI option | Purpose |
| --- | --- |
| `--config PATH` | Load a YAML configuration; defaults to `config.yaml`. Relative paths resolve from the repository root. |
| `--scenarios NAME [NAME ...]` | Choose one or more scenarios; defaults to all three. |
| `--zkp-backend groth16\|ideal` | Override the backend in the configuration. |
| `--skip-evm` | Skip contract execution and write zero gas measurements. |

For the built-in help, run `python run_experiments.py --help`.

## Configuration

Edit [config.yaml](config.yaml), or copy it and pass the copy to `--config`.

| Setting | Default | Meaning |
| --- | --- | --- |
| `simulation.students` / `selected` / `sessions` | `100` / `20` / `40` | Population, maximum selection size, and sessions per scenario |
| `simulation.seed` | `20260722` | Seed for simulated data and selection |
| `simulation.low_profile_ratio` | `0.30` | Fraction assigned the lower state-value profile |
| `simulation.low_online_probability` / `high_online_probability` | `0.40` / `0.90` | Connection probabilities for the two profiles |
| `simulation.gaussian_sigma` | `0.10` | Standard deviation of state noise |
| `simulation.malicious_ratio` | `0.20` | Fraction simulating false readiness claims |
| `selection.greedy_ratio` | `0.60` | Greedy portion of the configured selection size |
| `selection.beta1` / `beta2` | `0.50` / `0.50` | Weights for predicted attendance and past participation |
| `state.alpha1` / `alpha2` / `alpha3` | `0.40` / `0.30` / `0.30` | Weights in the squared state-prediction error |
| `state.epsilon_max` | `0.30` | Strict upper bound on readiness error |
| `state.eta` | `0.10` | Update rate for state estimates |
| `federated_learning.learning_rate` / `test_size` | `0.50` / `1200` | Local training rate and synthetic test-set size |
| `zkp.backend` | `groth16` | Default proof backend |
| `storage.output_dir` / `ipfs_dir` | `output` / `output/ipfs` | Report and content-addressed storage directories |

The configuration validator requires positive population/session counts, `selected <= students`, alpha and beta weights that each sum to one, a 3–8–1 model, exactly two local epochs, and a fixed-point scale of `1000`. For Groth16, choose alpha weights whose values rounded at that scale also sum to `1000`. The gas replay supports at most 109 selected students with its current account allocation.

The three artifact-path fields under `zkp` are currently loaded but are not passed to the proof service. The Python wrapper checks the bundled artifact locations; the Node service separately supports `ZKP_WASM`, `ZKP_ZKEY`, and `ZKP_VKEY` environment variables. Editing the YAML artifact paths alone does not relocate the artifacts.

## How a session works

1. **Generate observations.** Each simulated student receives a three-component private state, connection status, and attendance outcome. The malicious profile deliberately creates high-error readiness claims.
2. **Check readiness.** A connected student compares its state with the coordinator's estimate. In proof-enabled scenarios, the coordinator verifies the readiness proof, expected public inputs, enrolled identity commitment, and duplicate nullifiers before admitting candidates.
3. **Select students and issue a challenge.** The configured strategy chooses candidates, and the Python registry creates `keccak256(sessionId || nonce)` as the session challenge.
4. **Confirm attendance.** Attending students sign the challenge. The coordinator verifies their secp256k1 signatures before recording responses in the emulator.
5. **Train and aggregate.** Selected students train on their local history for two epochs and return model deltas. The coordinator aggregates them using sample-weighted FedAvg and updates its state estimates.
6. **Store and close.** The model and session log are saved by content identifier, and the registry records their CIDs when closing the session. After simulation, the optional EVM replay measures contract gas.

## Outputs and bundled results

| Path | Contents |
| --- | --- |
| `output/comparison_summary.csv` / `.json` | One summary row per scenario |
| `output/<scenario>/session_metrics.csv` | Selection, prediction error, model accuracy, proof timing, and gas by session |
| `output/<scenario>/zkp_logs.csv` | Proof generation time, verification time, and validity by student/session |
| `output/<scenario>/gas_logs.csv` | Start, submission, close, and total gas by session |
| `output/<scenario>/session_XX.json` | Session report, selected/confirmed students, and content identifiers |
| `output/ipfs/<scenario>/` | Content-addressed model snapshots (`.npz`) and logs (`.json`) |
| `output/evm_plan.json` / `evm_gas_results.json` | Replay plan and receipt-based gas results, written when EVM measurement runs |
| `output/plots/session_metrics.png` / `scenario_comparison.png` | Generated comparison plots |

The supplied archive includes the summary files, EVM plan, and gas results. The per-session files, content-addressed objects, and plots are generated when you run the experiments.

The bundled [comparison summary](output/comparison_summary.csv) reports:

| Scenario | Mean selection precision | Final FL accuracy | Mean gas per session |
| --- | ---: | ---: | ---: |
| `proposed` | 78.25% | 55.33% | 3,575,612 |
| `random` | 67.25% | 77.75% | 3,250,871 |
| `no_zkp` | 72.25% | 54.50% | 3,396,976 |

These are bundled simulation results, with gas rounded to the nearest unit. In this run, `proposed` leads on selection precision and `random` leads on final model accuracy.

Selection precision is confirmed attendance divided by the number selected. FL accuracy is evaluated on the synthetic test set. Proof acceptance measures the share of submitted proofs accepted, including deliberately malformed claims in the denominator; the bundled acceptance rate is about 79.16% in both proof-enabled scenarios. Proof metrics are empty/null when no proofs are submitted.

Gas covers session start, response submissions, and session close. It excludes contract deployment and off-chain proof work. Session wall-clock time excludes the later EVM replay. The Groth16 backend also caches proofs across scenarios and retains their original generation timings, so sequential scenario timings are not independent proof-performance benchmarks. Per-session JSON reports are written before gas is merged; use the CSV gas logs or comparison summaries for measured gas.

## Tests and circuit setup

Run the Python unit and integration tests:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

The suite covers wallet signatures and Keccak, fixed-point error calculations, content identifiers, the emulator's session lifecycle, MLP/FedAvg behavior, readiness-packet fields, public-input tampering, and a two-session integration run. It uses `IdealZKP`; the separate `zkp_smoke.mjs` and `evm_smoke.mjs` commands exercise real Groth16 proofs and local contract execution.

To generate circuit artifacts when they are missing:

```bash
node scripts/setup_zkp.mjs
```

The setup script exits early when its expected artifacts already exist. After editing the circuit, explicitly rebuild them:

```bash
ZKP_FORCE=1 node scripts/setup_zkp.mjs
node scripts/zkp_smoke.mjs
```

This recompiles the circuit and replaces its proving and verification artifacts using a local setup procedure. Treat those artifacts as course-project assets; the setup is not a production multiparty ceremony.

## Repository guide

| Path | Responsibility |
| --- | --- |
| [run_experiments.py](run_experiments.py) | CLI, scenario execution, gas replay, summaries, and plotting |
| [src/hybrid_attendance/](src/hybrid_attendance/) | Simulator, coordinator, student clients, MLP, cryptography, storage, and proof backends |
| [contracts/HybridAttendance.sol](contracts/HybridAttendance.sol) | Session lifecycle and attendance response registry |
| [circuits/readiness.circom](circuits/readiness.circom) | Groth16 readiness relation and identity/session binding |
| [scripts/](scripts/) | Circuit setup, proof service, Solidity compilation, gas replay, and smoke checks |
| [artifacts/zkp/](artifacts/zkp/) | Compiled circuit, witness utilities, and proving/verification keys |
| [tests/test_project.py](tests/test_project.py) | Python unit and integration tests |
| [report.pdf](report.pdf) | Project report in Persian |

## Scope and limitations

This is a research prototype with synthetic student data and simulated clients in one Python process. Its boundaries matter when interpreting the results:

- **Proofs establish a relation over a supplied witness.** They do not establish that device measurements are authentic. The simulated malicious client submits malformed proofs for high-error claims; this is a specific attack model.
- **Verification happens off-chain.** The Solidity contract checks selection, session state, duplicate responses, and nonempty signature bytes. It does not verify readiness proofs or recover the challenge signer. The gas scripts use random 65-byte response payloads, so they measure registry costs rather than end-to-end signature verification.
- **Storage is local.** `LocalIPFS` produces CID-addressed files without publishing or pinning them to an IPFS network.
- **Privacy is modeled at the client/coordinator boundary.** Raw states are omitted from readiness packets and published session logs, but the simulation itself has access to them. Federated updates use ordinary FedAvg; secure aggregation and differential privacy are not implemented.
- **Keys and setup are for experiments.** Wallet keys and identity secrets are derived deterministically from the simulation seed. Groth16 setup is generated locally.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Missing Python dependency | Activate `.venv` and run the Python dependency installation command above. |
| `No module named hybrid_attendance` during tests | Run from the repository root with `PYTHONPATH=src`. |
| `ZKP service returned no response` or an unexpected service exit | Check Node.js and local npm dependencies. Run `node scripts/zkp_service.mjs` directly to expose startup errors; stop it with Ctrl+C after diagnosis. |
| Missing ZKP artifacts | Run `node scripts/setup_zkp.mjs`. An older error message suggests `npm run zkp:setup`, but this snapshot has no root npm scripts. |
| An error involving `import.meta.dirname` | Use Node.js 22 or newer for the `.mjs` scripts. |
| Plotting fails in a headless environment | Prefix the experiment command with `MPLBACKEND=Agg`. |
| Gas is zero or proof metrics are empty | `--skip-evm` writes zero gas. Proof metrics are empty when no proofs are submitted, as in `no_zkp`. Timings from `ideal` are diagnostic timings. |

