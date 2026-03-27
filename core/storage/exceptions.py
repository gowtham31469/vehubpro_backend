"""Storage layer errors."""


class StorageError(Exception):
    """Base class for storage operations."""


class StorageConfigError(StorageError):
    """Invalid or incomplete storage configuration."""


class StorageValidationError(StorageError):
    """Uploaded file failed validation."""


class StorageUploadError(StorageError):
    """Upload or remote persistence failed."""
