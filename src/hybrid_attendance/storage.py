from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _varint(value: int) -> bytes:
    encoded = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        encoded.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(encoded)


def raw_cid_v1(data: bytes) -> str:
    """Return a standards-compliant CIDv1 for the raw codec and SHA2-256 multihash."""
    multihash = _varint(0x12) + _varint(32) + hashlib.sha256(data).digest()
    cid_bytes = _varint(1) + _varint(0x55) + multihash
    return "b" + base64.b32encode(cid_bytes).decode("ascii").lower().rstrip("=")


@dataclass(frozen=True)
class StoredObject:
    cid: str
    path: Path
    size: int


class LocalIPFS:
    """Content-addressed local store using valid raw CIDv1 identifiers."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def add_bytes(self, data: bytes, suffix: str = ".bin") -> StoredObject:
        cid = raw_cid_v1(data)
        path = self.root / f"{cid}{suffix}"
        if not path.exists():
            path.write_bytes(data)
        return StoredObject(cid=cid, path=path, size=len(data))

    def add_json(self, value: Any) -> StoredObject:
        return self.add_bytes(canonical_json_bytes(value), ".json")

    def verify(self, stored: StoredObject) -> bool:
        return stored.path.exists() and raw_cid_v1(stored.path.read_bytes()) == stored.cid

