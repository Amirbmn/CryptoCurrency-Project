from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .crypto import Wallet
from .ml import MLPModel
from .zkp import ProofEnvelope, ZKPBackend, fixed_weighted_error, make_public_inputs


BN128_FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617


@dataclass(frozen=True)
class ReadinessPacket:
    student_id: int
    ready: bool
    proof: ProofEnvelope | None


@dataclass
class StudentClient:
    student_id: int
    wallet: Wallet
    identity_secret: int
    identity_commitment: str
    low_profile: bool
    malicious: bool
    base_state: np.ndarray
    history_states: list[np.ndarray] = field(default_factory=list)
    history_labels: list[int] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        student_id: int,
        seed: int,
        low_profile: bool,
        malicious: bool,
        base_state: np.ndarray,
        zkp: ZKPBackend,
    ) -> "StudentClient":
        wallet = Wallet.deterministic(seed, student_id)
        identity_secret = int.from_bytes(
            hashlib.sha256(f"identity:{seed}:{student_id}".encode()).digest(), "big"
        ) % (BN128_FIELD - 1) + 1
        identity_commitment, _ = zkp.identity_binding(identity_secret, 0)
        return cls(
            student_id=student_id,
            wallet=wallet,
            identity_secret=identity_secret,
            identity_commitment=identity_commitment,
            low_profile=low_profile,
            malicious=malicious,
            base_state=np.asarray(base_state, dtype=float),
        )

    def prepare_readiness(
        self,
        session_id: int,
        connected: bool,
        real_state: np.ndarray,
        estimated_state: np.ndarray,
        alphas: tuple[float, float, float],
        epsilon_max: float,
        zkp: ZKPBackend,
        produce_proof: bool = True,
    ) -> tuple[ReadinessPacket, float]:
        _, local_error = fixed_weighted_error(real_state, estimated_state, alphas)
        honest_ready = connected and local_error < epsilon_max
        false_claim = connected and self.malicious and local_error >= epsilon_max
        ready = honest_ready or false_claim
        if not ready:
            return ReadinessPacket(self.student_id, False, None), local_error

        if not produce_proof:
            return ReadinessPacket(self.student_id, True, None), local_error

        _, nullifier = zkp.identity_binding(self.identity_secret, session_id)
        public_inputs = make_public_inputs(
            estimated_state,
            alphas,
            epsilon_max,
            session_id,
            self.identity_commitment,
            nullifier,
        )
        if honest_ready:
            proof = zkp.prove(real_state, self.identity_secret, public_inputs)
        else:
            # A high-error claimant cannot satisfy the circuit; send a malformed proof to exercise rejection.
            proof = ProofEnvelope(
                proof={"invalid": True},
                public_signals=["1", *(str(public_inputs[name]) for name in (
                    "shatE", "shatQ", "shatD", "alphaE", "alphaQ", "alphaD",
                    "errorBound", "sessionId", "identityCommitment", "nullifier"
                ))],
                public_inputs=public_inputs,
                generation_ms=0.0,
            )
        return ReadinessPacket(self.student_id, True, proof), local_error

    def sign_challenge(self, challenge: bytes) -> bytes:
        return self.wallet.sign(challenge)

    def add_local_example(self, state: np.ndarray, label: int) -> None:
        self.history_states.append(np.asarray(state, dtype=float).copy())
        self.history_labels.append(int(label))

    def local_update(
        self,
        global_model: MLPModel,
        epochs: int,
        learning_rate: float,
    ) -> tuple[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray], int]:
        x = np.asarray(self.history_states, dtype=float)
        y = np.asarray(self.history_labels, dtype=float)
        local_model = global_model.trained_copy(x, y, epochs=epochs, learning_rate=learning_rate)
        return local_model.delta_from(global_model), len(x)
