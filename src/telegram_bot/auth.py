"""
Authorization check (requirement #17/#12/#8 across all three phase docs:
the bot must only be usable by AUTHORIZED_USER_ID). Every handler in
handlers.py calls is_authorized() before doing anything else.
"""

from __future__ import annotations

import os


def is_authorized(user_id: int | str) -> bool:
    configured = os.environ.get("AUTHORIZED_USER_ID", "").strip()
    if not configured:
        return False
    return str(user_id) == configured
