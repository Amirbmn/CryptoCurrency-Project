from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

from hybrid_attendance.blockchain import BlockchainEmulator
from hybrid_attendance.config import load_config
from hybrid_attendance.crypto import Wallet, keccak_256
from hybrid_attendance.ml import MLPModel
from hybrid_attendance.simulator import ExperimentSimulator
from hybrid_attendance.storage import LocalIPFS, raw_cid_v1
from hybrid_attendance.student import StudentClient
from hybrid_attendance.zkp import IdealZKP, fixed_weighted_error, make_public_inputs


ROOT = Path(__file__).resolve().parents[1]


class CoreTests(unittest.TestCase):
    def test_required_default_configuration(self) -> None:
        config = load_config(ROOT / "config.yaml")
        self.assertEqual((config.simulation.students, config.simulation.selected, config.simulation.sessions), (100, 20, 40))
        self.assertEqual(config.federated_learning.local_epochs, 2)
        self.assertEqual(config.federated_learning.hidden_size, 8)
        self.assertAlmostEqual(sum(config.state.alphas), 1.0)

    def test_keccak_wallet_and_signature(self) -> None:
        self.assertEqual(
            keccak_256(b"").hex(),
            "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470",
        )
        wallet = Wallet.deterministic(10, 3)
        signature = wallet.sign(b"challenge")
        self.assertTrue(Wallet.verify(wallet.public_key, b"challenge", signature))
        self.assertFalse(Wallet.verify(wallet.public_key, b"other", signature))

    def test_fixed_point_formula_matches_weighted_mse(self) -> None:
        numerator, error = fixed_weighted_error(
            np.array([0.8, 0.7, 0.6]), np.array([0.5, 0.5, 0.5]), (0.4, 0.3, 0.3)
        )
        self.assertEqual(numerator, 51_000_000)
        self.assertAlmostEqual(error, 0.051)

    def test_cid_changes_with_content_and_verifies(self) -> None:
        self.assertNotEqual(raw_cid_v1(b"a"), raw_cid_v1(b"b"))
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalIPFS(directory)
            stored = storage.add_json({"session": 1})
            self.assertTrue(storage.verify(stored))

    def test_blockchain_lifecycle_and_duplicate_protection(self) -> None:
        chain = BlockchainEmulator()
        addresses = ["0x" + "11" * 20, "0x" + "22" * 20]
        challenge = chain.start_session(1, addresses, "bafyOld")
        self.assertEqual(len(challenge), 32)
        chain.submit_response(1, addresses[0], b"signature")
        with self.assertRaises(ValueError):
            chain.submit_response(1, addresses[0], b"duplicate")
        chain.close_session(1, "bafyModel", "bafyLog")
        self.assertFalse(chain.sessions[1].active)
        with self.assertRaises(ValueError):
            chain.submit_response(1, addresses[1], b"late")

    def test_mlp_architecture_and_fedavg_update(self) -> None:
        model = MLPModel.initialize(1)
        self.assertEqual(model.w1.shape, (3, 8))
        self.assertEqual(model.w2.shape, (8, 1))
        x = np.array([[0.1, 0.2, 0.3], [0.9, 0.8, 0.7]])
        y = np.array([0, 1])
        local = model.trained_copy(x, y, epochs=2, learning_rate=0.5)
        delta = local.delta_from(model)
        before = model.w1.copy()
        model.apply_weighted_deltas([(delta, len(x))])
        self.assertFalse(np.array_equal(before, model.w1))

    def test_readiness_packet_contains_no_private_state_or_error(self) -> None:
        zkp = IdealZKP()
        student = StudentClient.create(
            student_id=1,
            seed=7,
            low_profile=False,
            malicious=False,
            base_state=np.array([0.8, 0.8, 0.8]),
            zkp=zkp,
        )
        packet, local_error = student.prepare_readiness(
            1, True, np.array([0.8, 0.8, 0.8]), np.array([0.75, 0.75, 0.75]),
            (0.4, 0.3, 0.3), 0.3, zkp
        )
        self.assertLess(local_error, 0.3)
        serialized = repr(packet.__dict__)
        self.assertNotIn("real_state", serialized)
        self.assertNotIn("local_error", serialized)
        self.assertTrue(packet.ready)

    def test_public_input_tampering_is_rejected(self) -> None:
        zkp = IdealZKP()
        secret = 123
        commitment, nullifier = zkp.identity_binding(secret, 1)
        public = make_public_inputs(
            np.array([0.5, 0.5, 0.5]), (0.4, 0.3, 0.3), 0.3, 1, commitment, nullifier
        )
        proof = zkp.prove(np.array([0.55, 0.55, 0.55]), secret, public)
        valid, _ = zkp.verify(proof, public)
        self.assertTrue(valid)
        tampered = dict(public)
        tampered["shatE"] = 501
        valid, _ = zkp.verify(proof, tampered)
        self.assertFalse(valid)


class IntegrationTests(unittest.TestCase):
    def test_two_session_end_to_end_simulation(self) -> None:
        base = load_config(ROOT / "config.yaml")
        config = replace(
            base,
            simulation=replace(base.simulation, students=16, selected=4, sessions=2),
            federated_learning=replace(base.federated_learning, test_size=80),
            storage=replace(base.storage, output_dir="out", ipfs_dir="out/ipfs"),
        )
        with tempfile.TemporaryDirectory() as directory:
            simulator = ExperimentSimulator(config, "proposed", IdealZKP(), directory)
            result = simulator.run()
            self.assertEqual(len(result.session_metrics), 2)
            self.assertTrue(all(row["selected_count"] == 4 for row in result.session_metrics))
            self.assertTrue(all(row["model_cid"].startswith("bafk") for row in result.session_metrics))
            session_file = Path(directory) / "out/proposed/session_01.json"
            content = json.loads(session_file.read_text(encoding="utf-8"))
            self.assertIn("selected_students", content)
            self.assertNotIn("real_states", content)
            self.assertNotIn("student_errors", content)


if __name__ == "__main__":
    unittest.main()
