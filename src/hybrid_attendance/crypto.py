from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


_ROTATION = (
    0, 1, 62, 28, 27,
    36, 44, 6, 55, 20,
    3, 10, 43, 25, 39,
    41, 45, 15, 21, 8,
    18, 2, 61, 56, 14,
)
_ROUND_CONSTANTS = (
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A,
    0x8000000080008000, 0x000000000000808B, 0x0000000080000001,
    0x8000000080008081, 0x8000000000008009, 0x000000000000008A,
    0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
    0x8000000000008003, 0x8000000000008002, 0x8000000000000080,
    0x000000000000800A, 0x800000008000000A, 0x8000000080008081,
    0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
)
_MASK_64 = (1 << 64) - 1
_SECP256K1_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


def _rotate_left(value: int, shift: int) -> int:
    if shift == 0:
        return value & _MASK_64
    return ((value << shift) | (value >> (64 - shift))) & _MASK_64


def _keccak_f(state: list[int]) -> None:
    for rc in _ROUND_CONSTANTS:
        column = [state[x] ^ state[x + 5] ^ state[x + 10] ^ state[x + 15] ^ state[x + 20] for x in range(5)]
        delta = [column[(x - 1) % 5] ^ _rotate_left(column[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x + 5 * y] ^= delta[x]

        rotated = [0] * 25
        for x in range(5):
            for y in range(5):
                destination_x = y
                destination_y = (2 * x + 3 * y) % 5
                rotated[destination_x + 5 * destination_y] = _rotate_left(
                    state[x + 5 * y], _ROTATION[x + 5 * y]
                )

        for x in range(5):
            for y in range(5):
                state[x + 5 * y] = rotated[x + 5 * y] ^ (
                    (~rotated[(x + 1) % 5 + 5 * y]) & rotated[(x + 2) % 5 + 5 * y]
                )
                state[x + 5 * y] &= _MASK_64
        state[0] ^= rc


def keccak_256(data: bytes) -> bytes:
    """Ethereum Keccak-256 (not FIPS SHA3-256), implemented without external dependencies."""
    rate = 136
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != rate - 1:
        padded.append(0)
    padded.append(0x80)

    state = [0] * 25
    for offset in range(0, len(padded), rate):
        block = padded[offset : offset + rate]
        for lane in range(rate // 8):
            state[lane] ^= int.from_bytes(block[lane * 8 : lane * 8 + 8], "little")
        _keccak_f(state)
    return b"".join(lane.to_bytes(8, "little") for lane in state)[:32]


def _address_from_public_key(public_key: ec.EllipticCurvePublicKey) -> str:
    numbers = public_key.public_numbers()
    uncompressed_body = numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")
    return "0x" + keccak_256(uncompressed_body)[-20:].hex()


@dataclass
class Wallet:
    private_key: ec.EllipticCurvePrivateKey
    public_key: ec.EllipticCurvePublicKey
    address: str

    @classmethod
    def deterministic(cls, seed: int, student_id: int) -> "Wallet":
        digest = sha256(f"wallet:{seed}:{student_id}".encode()).digest()
        private_value = int.from_bytes(digest, "big") % (_SECP256K1_ORDER - 1) + 1
        private_key = ec.derive_private_key(private_value, ec.SECP256K1())
        public_key = private_key.public_key()
        return cls(private_key, public_key, _address_from_public_key(public_key))

    def sign(self, message: bytes) -> bytes:
        return self.private_key.sign(message, ec.ECDSA(hashes.SHA256()))

    @staticmethod
    def verify(public_key: ec.EllipticCurvePublicKey, message: bytes, signature: bytes) -> bool:
        try:
            public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
            return True
        except InvalidSignature:
            return False

