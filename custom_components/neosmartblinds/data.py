"""Runtime data attached to a config entry."""

from __future__ import annotations

from dataclasses import dataclass

from .buttons import ButtonController
from .hub import NeoHub


@dataclass
class NeoData:
    """Everything a running hub entry owns."""

    hub: NeoHub
    buttons: ButtonController
