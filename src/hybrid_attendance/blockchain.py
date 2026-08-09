from __future__ import annotations

from dataclasses import dataclass, field

from .crypto import keccak_256


@dataclass
class ChainSession:
    session_id: int
    challenge: bytes
    selected_addresses: list[str]
    previous_model_cid: str
    responses: dict[str, bytes] = field(default_factory=dict)
    model_cid: str = ""
    log_cid: str = ""
    active: bool = True


class BlockchainEmulator:
    """Behavioral twin of HybridAttendance.sol; gas is later read from real EVM receipts."""

    def __init__(self):
        self._nonce = 0
        self.sessions: dict[int, ChainSession] = {}

    def start_session(self, session_id: int, selected_addresses: list[str], previous_model_cid: str) -> bytes:
        if session_id in self.sessions:
            raise ValueError("session already exists")
        if not selected_addresses or len(set(selected_addresses)) != len(selected_addresses):
            raise ValueError("selection must be non-empty and unique")
        self._nonce += 1
        payload = session_id.to_bytes(32, "big") + self._nonce.to_bytes(32, "big")
        challenge = keccak_256(payload)
        self.sessions[session_id] = ChainSession(
            session_id=session_id,
            challenge=challenge,
            selected_addresses=list(selected_addresses),
            previous_model_cid=previous_model_cid,
        )
        return challenge

    def submit_response(self, session_id: int, student_address: str, signature: bytes) -> None:
        session = self.sessions[session_id]
        if not session.active:
            raise ValueError("session is closed")
        if student_address not in session.selected_addresses:
            raise ValueError("student is not selected")
        if not signature or student_address in session.responses:
            raise ValueError("invalid or duplicate response")
        session.responses[student_address] = signature

    def close_session(self, session_id: int, model_cid: str, log_cid: str) -> None:
        session = self.sessions[session_id]
        if not session.active or not model_cid or not log_cid:
            raise ValueError("session cannot be closed")
        session.model_cid = model_cid
        session.log_cid = log_cid
        session.active = False

