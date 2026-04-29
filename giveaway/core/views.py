from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union, TYPE_CHECKING

import discord
from discord import ButtonStyle, Interaction, TextStyle
from discord.ext import commands
from discord.ui import Button, Modal, TextInput, View
from discord.utils import MISSING

from .utils import duration_syntax, time_converter


if TYPE_CHECKING:
    from ..giveaway import Giveaway
    from .sessions import GiveawaySession

    ButtonCallbackT = Callable[[Union[Interaction, Any]], Awaitable]


_short_length = 256
_long_length = 4000
_field_value_length = 2048

GIFT = "\U0001F381"
TADA = "\U0001F389"
LOCK = "\U0001F512"


# ---------------------------------------------------------------------------
# Setup view (admin uses this to configure the giveaway before posting)
# ---------------------------------------------------------------------------


class GiveawayTextInput(TextInput):
    def __init__(self, name: str, **kwargs):
        self.name: str = name
        super().__init__(**kwargs)


class GiveawayModal(Modal):
    children: List[GiveawayTextInput]

    def __init__(self, view: "GiveawaySetupView"):
        super().__init__(title="Giveaway")
        self.view = view
        self.view.modals.append(self)
        for key, value in self.view.input_map.items():
            
