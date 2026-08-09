from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .blockchain import BlockchainEmulator
from .config import ProjectConfig
from .coordinator import Coordinator
from .storage import LocalIPFS, canonical_json_bytes
from .student import StudentClient
from .zkp import ZKPBackend


@dataclass
class ExperimentResult:
    scenario: str
    session_metrics: list[dict[str, Any]]
    zkp_logs: list[dict[str, Any]]
    evm_plan: list[dict[str, Any]]


def _attendance_probability(state: np.ndarray) -> float:
    logit = -4.0 + 2.4 * float(np.sum(state))
    return 1.0 / (1.0 + math.exp(-logit))


class ExperimentSimulator:
    def __init__(
        self,
        config: ProjectConfig,
        scenario: str,
        zkp: ZKPBackend,
        project_root: str | Path,
    ):
        if scenario not in {"proposed", "random", "no_zkp"}:
            raise ValueError(f"unknown scenario: {scenario}")
        self.config = config
        self.scenario = scenario
        self.zkp = zkp
        self.project_root = Path(project_root).resolve()
        self.output_dir = self.project_root / config.storage.output_dir / scenario
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.ipfs = LocalIPFS(self.project_root / config.storage.ipfs_dir / scenario)
        self.blockchain = BlockchainEmulator()
        self.students, initial_shat = self._create_students()
        self.coordinator = Coordinator(config, self.students, initial_shat)
        self.test_x, self.test_y = self._make_test_set()

    def _create_students(self) -> tuple[list[StudentClient], dict[int, np.ndarray]]:
        sim = self.config.simulation
        rng = np.random.default_rng(sim.seed)
        ids = np.arange(1, sim.students + 1)
        shuffled = rng.permutation(ids)
        low_count = int(round(sim.students * sim.low_profile_ratio))
        malicious_count = int(round(sim.students * sim.malicious_ratio))
        low_ids = set(int(value) for value in shuffled[:low_count])
        malicious_ids = set(int(value) for value in rng.permutation(ids)[:malicious_count])
        students: list[StudentClient] = []
        initial_shat: dict[int, np.ndarray] = {}

        for student_id in ids:
            low_profile = int(student_id) in low_ids
            base_rng = np.random.default_rng(sim.seed + 101 * int(student_id))
            if low_profile:
                base_state = base_rng.uniform(0.25, 0.55, size=3)
            else:
                base_state = base_rng.uniform(0.65, 0.90, size=3)
            students.append(
                StudentClient.create(
                    student_id=int(student_id),
                    seed=sim.seed,
                    low_profile=low_profile,
                    malicious=int(student_id) in malicious_ids,
                    base_state=base_state,
                    zkp=self.zkp,
                )
            )
            initial_shat[int(student_id)] = base_rng.uniform(0.35, 0.65, size=3)
        return students, initial_shat

    def _make_test_set(self) -> tuple[np.ndarray, np.ndarray]:
        cfg = self.config.federated_learning
        sim = self.config.simulation
        rng = np.random.default_rng(self.config.simulation.seed + 999_983)
        low = rng.random(cfg.test_size) < sim.low_profile_ratio
        x = np.empty((cfg.test_size, 3), dtype=float)
        x[low] = rng.uniform(0.25, 0.55, size=(int(low.sum()), 3))
        x[~low] = rng.uniform(0.65, 0.90, size=(int((~low).sum()), 3))
        x = np.clip(x + rng.normal(0.0, sim.gaussian_sigma, size=x.shape), 0.0, 1.0)
        probabilities = np.asarray([_attendance_probability(state) for state in x])
        online = np.where(low, sim.low_online_probability, sim.high_online_probability)
        y = (rng.random(cfg.test_size) < probabilities * online).astype(int)
        return x, y

    def _observation(self, student: StudentClient, session_id: int) -> tuple[np.ndarray, bool, int]:
        sim = self.config.simulation
        rng = np.random.default_rng(sim.seed + session_id * 100_003 + student.student_id * 997)
        real_state = np.clip(
            student.base_state + rng.normal(0.0, sim.gaussian_sigma, size=3), 0.0, 1.0
        )
        if student.malicious:
            # Security experiment required by the assignment: malicious clients use a
            # state deliberately far from the published estimate and still claim ready.
            estimate = self.coordinator.shat[student.student_id]
            endpoint = np.where(estimate >= 0.5, 0.0, 1.0)
            real_state = np.clip(endpoint + rng.normal(0.0, sim.gaussian_sigma / 4, size=3), 0.0, 1.0)
        online_probability = (
            sim.low_online_probability if student.low_profile else sim.high_online_probability
        )
        connected = bool(rng.random() < online_probability)
        attendance_probability = _attendance_probability(real_state)
        if student.malicious:
            attendance_probability *= 0.15
        attended = int(connected and rng.random() < attendance_probability)
        return real_state, connected, attended

    def run(self) -> ExperimentResult:
        session_metrics: list[dict[str, Any]] = []
        all_zkp_logs: list[dict[str, Any]] = []
        evm_plan: list[dict[str, Any]] = []
        initial_model = self.ipfs.add_bytes(self.coordinator.global_model.to_bytes(), ".npz")
        previous_model_cid = initial_model.cid

        for session_id in range(1, self.config.simulation.sessions + 1):
            session_started = time.perf_counter()
            observations: dict[int, tuple[np.ndarray, bool, int]] = {}
            packets = []
            local_errors = []
            use_zkp = self.scenario != "no_zkp"

            for student in self.students:
                real_state, connected, attended = self._observation(student, session_id)
                observations[student.student_id] = real_state, connected, attended
                packet, local_error = student.prepare_readiness(
                    session_id=session_id,
                    connected=connected,
                    real_state=real_state,
                    estimated_state=self.coordinator.shat[student.student_id],
                    alphas=self.config.state.alphas,
                    epsilon_max=self.config.state.epsilon_max,
                    zkp=self.zkp,
                    produce_proof=use_zkp,
                )
                packets.append(packet)
                local_errors.append(local_error)

            valid_candidates, zkp_logs = self.coordinator.validate_packets(
                session_id, packets, self.zkp, use_zkp=use_zkp
            )
            for entry in zkp_logs:
                entry["scenario"] = self.scenario
            all_zkp_logs.extend(zkp_logs)
            selected, scored = self.coordinator.select_students(
                valid_candidates, self.scenario, session_id
            )
            if not selected:
                raise RuntimeError(f"session {session_id} has no selectable student")

            selected_addresses = [self.students[student_id - 1].wallet.address for student_id in selected]
            challenge = self.blockchain.start_session(
                session_id, selected_addresses, previous_model_cid
            )
            confirmed: list[int] = []
            for student_id in selected:
                student = self.students[student_id - 1]
                attended = observations[student_id][2]
                if not attended:
                    continue
                signature = student.sign_challenge(challenge)
                if self.coordinator.verify_signature(student_id, challenge, signature):
                    self.blockchain.submit_response(session_id, student.wallet.address, signature)
                    confirmed.append(student_id)

            outcomes = {student_id: observation[2] for student_id, observation in observations.items()}
            for student in self.students:
                student.add_local_example(observations[student.student_id][0], outcomes[student.student_id])

            fl_cfg = self.config.federated_learning
            # Every selected client was connected when it sent readiness; it can therefore
            # return a local delta even if its later attendance signature times out.
            updates = [
                self.students[student_id - 1].local_update(
                    self.coordinator.global_model,
                    epochs=fl_cfg.local_epochs,
                    learning_rate=fl_cfg.learning_rate,
                )
                for student_id in selected
            ]
            self.coordinator.aggregate_updates(updates)
            self.coordinator.finish_session(outcomes)
            fl_accuracy = self.coordinator.global_model.accuracy(self.test_x, self.test_y)

            model_object = self.ipfs.add_bytes(self.coordinator.global_model.to_bytes(), ".npz")
            received = len(zkp_logs)
            valid_proofs = sum(bool(item["valid"]) for item in zkp_logs)
            log_document = {
                "session_id": session_id,
                "scenario": self.scenario,
                "challenge": "0x" + challenge.hex(),
                "selected_students": selected,
                "confirmed_students": confirmed,
                "candidate_count": len(valid_candidates),
                "selection_precision": len(confirmed) / len(selected),
                "fl_accuracy": fl_accuracy,
                "zkp_received": received,
                "zkp_valid": valid_proofs,
                "model_cid": model_object.cid,
            }
            log_object = self.ipfs.add_json(log_document)
            if not self.ipfs.verify(model_object) or not self.ipfs.verify(log_object):
                raise RuntimeError("content-addressed storage verification failed")
            self.blockchain.close_session(session_id, model_object.cid, log_object.cid)

            wall_clock = time.perf_counter() - session_started
            verification_times = [float(item["verification_ms"]) for item in zkp_logs]
            generation_times = [float(item["proof_generation_ms"]) for item in zkp_logs]
            metric = {
                "scenario": self.scenario,
                "session_id": session_id,
                "selected_count": len(selected),
                "confirmed_count": len(confirmed),
                "selection_precision": len(confirmed) / len(selected),
                "mean_prediction_error": float(np.mean(local_errors)),
                "fl_accuracy": fl_accuracy,
                "start_gas": 0,
                "submit_gas": 0,
                "close_gas": 0,
                "total_gas": 0,
                "wall_clock_seconds": wall_clock,
                "zkp_received": received,
                "zkp_valid": valid_proofs,
                "zkp_success_rate": (valid_proofs / received) if received else float("nan"),
                "avg_zkp_generation_ms": float(np.mean(generation_times)) if generation_times else float("nan"),
                "avg_zkp_verification_ms": float(np.mean(verification_times)) if verification_times else float("nan"),
                "model_cid": model_object.cid,
                "log_cid": log_object.cid,
            }
            session_metrics.append(metric)
            final_report = {**log_document, "metrics": metric, "log_cid": log_object.cid}
            (self.output_dir / f"session_{session_id:02d}.json").write_bytes(
                canonical_json_bytes(final_report)
            )
            evm_plan.append(
                {
                    "session_id": session_id,
                    "selected_count": len(selected),
                    "response_count": len(confirmed),
                    "previous_model_cid": previous_model_cid,
                    "model_cid": model_object.cid,
                    "log_cid": log_object.cid,
                }
            )
            previous_model_cid = model_object.cid

        return ExperimentResult(self.scenario, session_metrics, all_zkp_logs, evm_plan)
