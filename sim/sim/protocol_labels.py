"""Human-readable protocol labels for simulation reports."""

import re

from .types import Protocol


PROTOCOL_DISPLAY_LABELS = {
    "acp": "ACP",
    "ap2": "AP2",
    "x402": "x402",
    "mpp": "Stripe MPP",
    "atxp": "ATXP",
    "cdp": "CDP",
}


def protocol_display_label(protocol: object, default: str = "unknown") -> str:
    """Return the display label for a protocol without changing raw payload keys."""
    if isinstance(protocol, Protocol):
        key = protocol.value
    elif protocol:
        key = str(protocol).strip()
    else:
        return default

    return PROTOCOL_DISPLAY_LABELS.get(key.lower(), key.upper())


def protocol_list_label(value: object, default: str = "unknown") -> str:
    if isinstance(value, (list, tuple, set)):
        labels = [protocol_display_label(item, "") for item in value if str(item)]
        return ", ".join(label for label in labels if label) or default
    return protocol_display_label(value, default)


_PROTOCOL_TOKEN_RE = re.compile(
    r"\b(" + "|".join(re.escape(key) for key in sorted(PROTOCOL_DISPLAY_LABELS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


def normalize_protocol_labels_in_text(text: str) -> str:
    return _PROTOCOL_TOKEN_RE.sub(lambda match: protocol_display_label(match.group(0)), text)
