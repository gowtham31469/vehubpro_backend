"""PII encryption with key rotation support."""
from __future__ import annotations

import hashlib
import os
from typing import Dict, Tuple

from cryptography.fernet import Fernet, InvalidToken
from django.core.exceptions import ImproperlyConfigured


class PIIEncryptor:
    """
    Fernet-based PII encryption with explicit key versioning.

    Env format:
      PII_ENCRYPTION_KEYS="v1:base64key,v2:base64key"
      PII_ACTIVE_KEY="v2"
    """

    def __init__(self) -> None:
        self._keys: Dict[str, Fernet] = {}
        self._active_version: str = ""
        self._load_keys()

    def _load_keys(self) -> None:
        raw_keys = os.getenv("PII_ENCRYPTION_KEYS", "").strip()
        active_version = os.getenv("PII_ACTIVE_KEY", "").strip()

        if not raw_keys:
            raise ImproperlyConfigured("PII_ENCRYPTION_KEYS environment variable is missing.")
        if not active_version:
            raise ImproperlyConfigured("PII_ACTIVE_KEY environment variable is missing.")

        try:
            for key_pair in raw_keys.split(","):
                version, key = key_pair.split(":", 1)
                version = version.strip()
                key = key.strip()
                if not version or not key:
                    raise ValueError("Empty key version or key.")
                self._keys[version] = Fernet(key.encode())
        except Exception as exc:
            raise ImproperlyConfigured(f"Invalid PII_ENCRYPTION_KEYS format: {exc}") from exc

        if active_version not in self._keys:
            raise ImproperlyConfigured(
                f"PII_ACTIVE_KEY '{active_version}' not present in PII_ENCRYPTION_KEYS."
            )
        self._active_version = active_version

    @property
    def active_version(self) -> str:
        return self._active_version

    def encrypt(self, value: str) -> Tuple[str, str]:
        if not value:
            return "", self._active_version
        token = self._keys[self._active_version].encrypt(value.encode()).decode()
        return token, self._active_version

    def decrypt(self, encrypted_value: str, key_version: str) -> str:
        if not encrypted_value:
            return ""
        if key_version not in self._keys:
            raise ValueError(f"Unknown key version '{key_version}'.")
        try:
            return self._keys[key_version].decrypt(encrypted_value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Unable to decrypt value with provided key version.") from exc

    def rotate(self, encrypted_value: str, from_key_version: str) -> Tuple[str, str]:
        """
        Re-encrypt an existing token with the active key version.
        """
        plain = self.decrypt(encrypted_value, from_key_version)
        return self.encrypt(plain)

    @staticmethod
    def hash_value(value: str) -> str:
        if not value:
            return ""
        return hashlib.sha256(value.lower().strip().encode()).hexdigest()


pii_encryptor = PIIEncryptor()
