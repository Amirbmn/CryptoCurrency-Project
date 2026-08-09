from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SimulationConfig:
    students: int
    selected: int
    sessions: int
    seed: int
    low_profile_ratio: float
    low_online_probability: float
    high_online_probability: float
    gaussian_sigma: float
    malicious_ratio: float


@dataclass(frozen=True)
class SelectionConfig:
    greedy_ratio: float
    beta1: float
    beta2: float


@dataclass(frozen=True)
class StateConfig:
    alpha1: float
    alpha2: float
    alpha3: float
    epsilon_max: float
    eta: float
    fixed_point_scale: int

    @property
    def alphas(self) -> tuple[float, float, float]:
        return self.alpha1, self.alpha2, self.alpha3


@dataclass(frozen=True)
class FederatedLearningConfig:
    input_size: int
    hidden_size: int
    local_epochs: int
    learning_rate: float
    test_size: int


@dataclass(frozen=True)
class ZKPConfig:
    backend: str
    wasm_path: str
    zkey_path: str
    verification_key_path: str


@dataclass(frozen=True)
class StorageConfig:
    output_dir: str
    ipfs_dir: str


@dataclass(frozen=True)
class ProjectConfig:
    simulation: SimulationConfig
    selection: SelectionConfig
    state: StateConfig
    federated_learning: FederatedLearningConfig
    zkp: ZKPConfig
    storage: StorageConfig

    def validate(self) -> None:
        sim = self.simulation
        if sim.students <= 0 or sim.selected <= 0 or sim.sessions <= 0:
            raise ValueError("students, selected and sessions must be positive")
        if sim.selected > sim.students:
            raise ValueError("selected students cannot exceed total students")
        for name, value in {
            "low_profile_ratio": sim.low_profile_ratio,
            "low_online_probability": sim.low_online_probability,
            "high_online_probability": sim.high_online_probability,
            "malicious_ratio": sim.malicious_ratio,
            "greedy_ratio": self.selection.greedy_ratio,
        }.items():
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if abs(sum(self.state.alphas) - 1.0) > 1e-9:
            raise ValueError("alpha1 + alpha2 + alpha3 must equal 1")
        if abs(self.selection.beta1 + self.selection.beta2 - 1.0) > 1e-9:
            raise ValueError("beta1 + beta2 must equal 1")
        if self.federated_learning.input_size != 3 or self.federated_learning.hidden_size != 8:
            raise ValueError("the required MLP architecture is exactly 3-8-1")
        if self.federated_learning.local_epochs != 2:
            raise ValueError("the assignment requires exactly two local epochs")
        if self.state.fixed_point_scale != 1000:
            raise ValueError("the supplied Circom circuit uses a fixed-point scale of 1000")


def _make(dataclass_type: type[Any], raw: dict[str, Any]) -> Any:
    return dataclass_type(**raw)


def load_config(path: str | Path) -> ProjectConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config = ProjectConfig(
        simulation=_make(SimulationConfig, raw["simulation"]),
        selection=_make(SelectionConfig, raw["selection"]),
        state=_make(StateConfig, raw["state"]),
        federated_learning=_make(FederatedLearningConfig, raw["federated_learning"]),
        zkp=_make(ZKPConfig, raw["zkp"]),
        storage=_make(StorageConfig, raw["storage"]),
    )
    config.validate()
    return config

