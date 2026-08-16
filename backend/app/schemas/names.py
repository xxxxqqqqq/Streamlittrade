"""Shared validation for user-facing research asset names."""

import re


def reject_corrupted_display_name(value: str) -> str:
    """Reject common encoding-loss markers before immutable assets are created."""

    normalized = value.strip()
    if "\ufffd" in normalized or re.search(r"[?？]{2,}", normalized):
        raise ValueError("名称疑似发生字符编码损坏，请使用完整、正式的中英文名称")
    return normalized
