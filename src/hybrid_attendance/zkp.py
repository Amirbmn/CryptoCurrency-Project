from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np


PUBLIC_SIGNAL_NAMES = (
    "shatE",
    "shatQ",
    "shatD",
    "alphaE",
    "alphaQ",
    "alphaD",
    "errorBound",
    "sessionId",
    "identityCommitment",
    "nullifier",
)


def quantize(values: np.ndarray | tuple[float, ...], scale: int = 1000) -> tuple[int, ...]:
    array = np.clip(np.asarray(values, dtype=float), 0.0, 1.0)
    return tuple(int(round(value * scale)) for value in array)


def fixed_weighted_error(
    real_state: np.ndarray,
    estimated_state: np.ndarray,
    alphas: tuple[float, float, float],
    scale: int = 1000,
) -> tuple[int, float]:
    real = np.asarray(quantize(real_state, scale), dtype=np.int64)
    estimated = np.asarray(quantize(estimated_state, scale), dtype=np.int64)
    alpha_fixed = np.asarray([int(round(value * scale)) for value in alphas], dtype=np.int64)
    numerator = int(np.sum(alpha_fixed * np.square(real - estimated)))
    return numerator, numerator / float(scale**3)


def error_bound(epsilon_max: float, scale: int = 1000) -> int:
    return int(round(epsilon_max * scale)) * scale * scale


def expected_public_signals(public_inputs: dict[str, int | str]) -> list[str]:
    # Circom emits outputs first and then the public inputs in declaration order.
    return ["1", *(str(public_inputs[name]) for name in PUBLIC_SIGNAL_NAMES)]


@dataclass
class ProofEnvelope:
    proof: dict[str, Any]
    public_signals: list[str]
    public_inputs: dict[str, int | str]
    generation_ms: float


class ZKPBackend(Protocol):
    def identity_binding(self, identity_secret: int, session_id: int) -> tuple[str, str]: ...
    def prove(
        self,
        real_state: np.ndarray,
        identity_secret: int,
        public_inputs: dict[str, int | str],
    ) -> ProofEnvelope: ...
    def verify(self, envelope: ProofEnvelope, expected_inputs: dict[str, int | str]) -> tuple[bool, float]: ...
    def close(self) -> None: ...


class Groth16Service:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        required = [
            self.project_root / "artifacts/zkp/readiness_js/readiness.wasm",
            self.project_root / "artifacts/zkp/readiness_final.zkey",
            self.project_root / "artifacts/zkp/verification_key.json",
        ]
        missing = [str(path) for path in required if not path.exists()]
        if missing:
            raise FileNotFoundError("missing ZKP artifacts; run `npm run zkp:setup`: " + ", ".join(missing))
        self.process = subprocess.Popen(
            ["node", str(self.project_root / "scripts/zkp_service.mjs")],
            cwd=self.project_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self.request_id = 0
        self.call("health")

    def call(self, operation: str, **payload: Any) -> dict[str, Any]:
        if self.process.poll() is not None:
            raise RuntimeError("ZKP service exited unexpectedly")
        self.request_id += 1
        message = {"id": self.request_id, "op": operation, **payload}
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("ZKP service returned no response")
        response = json.loads(line)
        if not response.get("ok"):
            raise RuntimeError(response.get("error", "unknown ZKP service error"))
        return response["result"]

    def close(self) -> None:
        if self.process.poll() is None:
            assert self.process.stdin is not None
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=5)


class Groth16ZKP:
    """Actual Groth16 prover/verifier backed by the Circom readiness circuit."""

    def __init__(self, project_root: str | Path):
        self.service = Groth16Service(project_root)
        self.binding_cache: dict[tuple[int, int], tuple[str, str]] = {}
        self.proof_cache: dict[str, ProofEnvelope] = {}

    def identity_binding(self, identity_secret: int, session_id: int) -> tuple[str, str]:
        key = identity_secret, session_id
        if key not in self.binding_cache:
            result = self.service.call(
                "identity", identitySecret=str(identity_secret), sessionId=session_id
            )
            self.binding_cache[key] = result["identityCommitment"], result["nullifier"]
        return self.binding_cache[key]

    def prove(
        self,
        real_state: np.ndarray,
        identity_secret: int,
        public_inputs: dict[str, int | str],
    ) -> ProofEnvelope:
        real = quantize(real_state)
        circuit_input = {
            "E": real[0],
            "Q": real[1],
            "D": real[2],
            "identitySecret": str(identity_secret),
            **public_inputs,
        }
        cache_key = hashlib.sha256(
            json.dumps(circuit_input, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if cache_key not in self.proof_cache:
            result = self.service.call("prove", input=circuit_input)
            self.proof_cache[cache_key] = ProofEnvelope(
                proof=result["proof"],
                public_signals=[str(value) for value in result["publicSignals"]],
                public_inputs=copy.deepcopy(public_inputs),
                generation_ms=float(result["proofMs"]),
            )
        return copy.deepcopy(self.proof_cache[cache_key])

    def verify(self, envelope: ProofEnvelope, expected_inputs: dict[str, int | str]) -> tuple[bool, float]:
        expected = expected_public_signals(expected_inputs)
        result = self.service.call(
            "verify",
            proof=envelope.proof,
            publicSignals=envelope.public_signals,
            expectedPublicSignals=expected,
        )
        return bool(result["valid"]), float(result["verifyMs"])

    def close(self) -> None:
        self.service.close()


class IdealZKP:
    """Circuit-equivalent fast backend used only by unit tests and quick diagnostics."""

    def identity_binding(self, identity_secret: int, session_id: int) -> tuple[str, str]:
        commitment = int.from_bytes(hashlib.sha256(f"id:{identity_secret}".encode()).digest(), "big")
        nullifier = int.from_bytes(
            hashlib.sha256(f"null:{identity_secret}:{session_id}".encode()).digest(), "big"
        )
        return str(commitment), str(nullifier)

    def prove(
        self,
        real_state: np.ndarray,
        identity_secret: int,
        public_inputs: dict[str, int | str],
    ) -> ProofEnvelope:
        started = time.perf_counter_ns()
        real = np.asarray(quantize(real_state), dtype=np.int64)
        estimate = np.asarray(
            [public_inputs["shatE"], public_inputs["shatQ"], public_inputs["shatD"]], dtype=np.int64
        )
        alpha = np.asarray(
            [public_inputs["alphaE"], public_inputs["alphaQ"], public_inputs["alphaD"]], dtype=np.int64
        )
        valid = int(np.sum(alpha * np.square(real - estimate))) < int(public_inputs["errorBound"])
        if not valid:
            raise ValueError("witness does not satisfy readiness relation")
        elapsed = (time.perf_counter_ns() - started) / 1e6
        return ProofEnvelope(
            proof={"ideal_test_proof": True},
            public_signals=expected_public_signals(public_inputs),
            public_inputs=copy.deepcopy(public_inputs),
            generation_ms=elapsed,
        )

    def verify(self, envelope: ProofEnvelope, expected_inputs: dict[str, int | str]) -> tuple[bool, float]:
        started = time.perf_counter_ns()
        valid = (
            envelope.proof.get("ideal_test_proof") is True
            and envelope.public_signals == expected_public_signals(expected_inputs)
        )
        return valid, (time.perf_counter_ns() - started) / 1e6

    def close(self) -> None:
        return None


def make_public_inputs(
    estimated_state: np.ndarray,
    alphas: tuple[float, float, float],
    epsilon_max: float,
    session_id: int,
    identity_commitment: str,
    nullifier: str,
    scale: int = 1000,
) -> dict[str, int | str]:
    estimate = quantize(estimated_state, scale)
    alpha = tuple(int(round(value * scale)) for value in alphas)
    return {
        "shatE": estimate[0],
        "shatQ": estimate[1],
        "shatD": estimate[2],
        "alphaE": alpha[0],
        "alphaQ": alpha[1],
        "alphaD": alpha[2],
        "errorBound": error_bound(epsilon_max, scale),
        "sessionId": session_id,
        "identityCommitment": identity_commitment,
        "nullifier": nullifier,
    }

