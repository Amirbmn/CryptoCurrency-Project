from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np


def _sigmoid(value: np.ndarray) -> np.ndarray:
    clipped = np.clip(value, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-clipped))


@dataclass
class MLPModel:
    w1: np.ndarray
    b1: np.ndarray
    w2: np.ndarray
    b2: np.ndarray

    @classmethod
    def initialize(cls, seed: int, hidden_size: int = 8) -> "MLPModel":
        rng = np.random.default_rng(seed)
        return cls(
            w1=rng.normal(0, 0.25, size=(3, hidden_size)),
            b1=np.zeros(hidden_size, dtype=float),
            w2=rng.normal(0, 0.25, size=(hidden_size, 1)),
            b2=np.zeros(1, dtype=float),
        )

    def copy(self) -> "MLPModel":
        return MLPModel(*(array.copy() for array in self.arrays()))

    def arrays(self) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        return self.w1, self.b1, self.w2, self.b2

    def predict_proba(self, x: np.ndarray) -> np.ndarray:
        data = np.atleast_2d(np.asarray(x, dtype=float))
        hidden = np.maximum(data @ self.w1 + self.b1, 0.0)
        return _sigmoid(hidden @ self.w2 + self.b2).reshape(-1)

    def accuracy(self, x: np.ndarray, y: np.ndarray) -> float:
        prediction = (self.predict_proba(x) >= 0.5).astype(int)
        return float(np.mean(prediction == np.asarray(y, dtype=int)))

    def trained_copy(self, x: np.ndarray, y: np.ndarray, epochs: int, learning_rate: float) -> "MLPModel":
        model = self.copy()
        data = np.asarray(x, dtype=float)
        labels = np.asarray(y, dtype=float).reshape(-1, 1)
        if len(data) == 0:
            return model

        for _ in range(epochs):
            z1 = data @ model.w1 + model.b1
            hidden = np.maximum(z1, 0.0)
            predictions = _sigmoid(hidden @ model.w2 + model.b2)
            output_gradient = (predictions - labels) / len(data)
            grad_w2 = hidden.T @ output_gradient
            grad_b2 = output_gradient.sum(axis=0)
            hidden_gradient = (output_gradient @ model.w2.T) * (z1 > 0)
            grad_w1 = data.T @ hidden_gradient
            grad_b1 = hidden_gradient.sum(axis=0)

            model.w1 -= learning_rate * np.clip(grad_w1, -2.0, 2.0)
            model.b1 -= learning_rate * np.clip(grad_b1, -2.0, 2.0)
            model.w2 -= learning_rate * np.clip(grad_w2, -2.0, 2.0)
            model.b2 -= learning_rate * np.clip(grad_b2, -2.0, 2.0)
        return model

    def delta_from(self, global_model: "MLPModel") -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        return tuple(local - global_array for local, global_array in zip(self.arrays(), global_model.arrays()))

    def apply_weighted_deltas(
        self,
        updates: list[tuple[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray], int]],
    ) -> None:
        if not updates:
            return
        total_samples = sum(sample_count for _, sample_count in updates)
        if total_samples == 0:
            return
        aggregated = [np.zeros_like(array) for array in self.arrays()]
        for delta, sample_count in updates:
            weight = sample_count / total_samples
            for index, component in enumerate(delta):
                aggregated[index] += component * weight
        for parameter, change in zip(self.arrays(), aggregated):
            parameter += change

    def to_bytes(self) -> bytes:
        buffer = io.BytesIO()
        np.savez_compressed(buffer, w1=self.w1, b1=self.b1, w2=self.w2, b2=self.b2)
        return buffer.getvalue()

