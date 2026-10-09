"""Render only the saved frozen bundle, with no live audit connection."""
from .publish import publish_frozen


def render(bundle, *, output, receipt_output=None):
    return publish_frozen(bundle, output=output, receipt_output=receipt_output)


__all__ = ["render"]
