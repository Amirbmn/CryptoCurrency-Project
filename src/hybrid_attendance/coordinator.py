from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from .config import ProjectConfig
from .crypto import Wallet
from .ml import MLPModel
from .student import ReadinessPacket, StudentClient
from .zkp import ZKPBackend, make_public_inputs


@dataclass(frozen=True)
class Candidate:
    student_id: int
    probability: float
    participation: float
    utility: float


class Coordinator:
    def __init__(self, config: ProjectConfig, students: Iterable[StudentClient], initial_shat: dict[int, np.ndarray]):
        self.config = config
        self.students = {student.student_id: student for student in students}
        self.public_keys = {student.student_id: student.wallet.public_key for student in students}
        self.identity_commitments = {
            student.student_id: student.identity_commitment for student in students
        }
        self.shat = {student_id: value.copy() for student_id, value in initial_shat.items()}
        self.global_model = MLPModel.initialize(config.simulation.seed, config.federated_learning.hidden_size)
        self.successful_attendance = {student_id: 0 for student_id in self.students}
        self.sessions_completed = 0

    def probabilities(self) -> dict[int, float]:
        return {
            student_id: float(self.global_model.predict_proba(state)[0])
            for student_id, state in self.shat.items()
        }

    def participation_values(self) -> dict[int, float]:
        if self.sessions_completed == 0:
            return {student_id: 0.0 for student_id in self.students}
        return {
            student_id: self.successful_attendance[student_id] / self.sessions_completed
            for student_id in self.students
        }

    def validate_packets(
        self,
        session_id: int,
        packets: list[ReadinessPacket],
        zkp: ZKPBackend,
        use_zkp: bool,
    ) -> tuple[list[int], list[dict[str, object]]]:
        valid_students: list[int] = []
        logs: list[dict[str, object]] = []
        seen_nullifiers: set[str] = set()
        state = self.config.state

        for packet in packets:
            if not packet.ready:
                continue
            if not use_zkp:
                valid_students.append(packet.student_id)
                continue

            proof = packet.proof
            if proof is None or packet.student_id not in self.students:
                continue
            supplied = proof.public_inputs
            nullifier = str(supplied.get("nullifier", ""))
            expected = make_public_inputs(
                self.shat[packet.student_id],
                state.alphas,
                state.epsilon_max,
                session_id,
                self.identity_commitments[packet.student_id],
                nullifier,
            )
            metadata_matches = supplied == expected and nullifier not in seen_nullifiers
            if metadata_matches:
                valid, verification_ms = zkp.verify(proof, expected)
            else:
                valid, verification_ms = False, 0.0
            if valid:
                seen_nullifiers.add(nullifier)
                valid_students.append(packet.student_id)
            logs.append(
                {
                    "session_id": session_id,
                    "student_id": packet.student_id,
                    "proof_generation_ms": proof.generation_ms,
                    "verification_ms": verification_ms,
                    "valid": bool(valid),
                }
            )
        return valid_students, logs

    def select_students(
        self,
        candidates: list[int],
        scenario: str,
        session_id: int,
    ) -> tuple[list[int], list[Candidate]]:
        probability = self.probabilities()
        participation = self.participation_values()
        selection_cfg = self.config.selection
        scored = [
            Candidate(
                student_id=student_id,
                probability=probability[student_id],
                participation=participation[student_id],
                utility=selection_cfg.beta1 * probability[student_id]
                + selection_cfg.beta2 * participation[student_id],
            )
            for student_id in candidates
        ]
        k = min(self.config.simulation.selected, len(scored))
        rng = np.random.default_rng(self.config.simulation.seed + 17_000 * session_id)
        if scenario == "random":
            selected = [] if k == 0 else [
                int(value) for value in rng.choice(candidates, size=k, replace=False)
            ]
            return selected, scored

        sorted_candidates = sorted(scored, key=lambda candidate: (-candidate.utility, candidate.student_id))
        greedy_count = min(int(round(self.config.simulation.selected * selection_cfg.greedy_ratio)), k)
        greedy = [candidate.student_id for candidate in sorted_candidates[:greedy_count]]
        remaining = [candidate.student_id for candidate in sorted_candidates[greedy_count:]]
        random_count = k - len(greedy)
        random_part = [] if random_count == 0 else [
            int(value) for value in rng.choice(remaining, size=random_count, replace=False)
        ]
        return greedy + random_part, scored

    def verify_signature(self, student_id: int, challenge: bytes, signature: bytes) -> bool:
        return Wallet.verify(self.public_keys[student_id], challenge, signature)

    def aggregate_updates(
        self,
        updates: list[tuple[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray], int]],
    ) -> None:
        self.global_model.apply_weighted_deltas(updates)

    def finish_session(self, outcomes: dict[int, int]) -> None:
        eta = self.config.state.eta
        for student_id, outcome in outcomes.items():
            estimate = self.shat[student_id]
            if outcome == 1:
                estimate = estimate + eta * (1.0 - estimate)
                self.successful_attendance[student_id] += 1
            else:
                estimate = estimate - eta * estimate
            self.shat[student_id] = np.clip(estimate, 0.0, 1.0)
        self.sessions_completed += 1
