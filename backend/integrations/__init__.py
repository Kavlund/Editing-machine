"""Client integrations (Notion CPS + Google Drive).

All integrations are OFF until the client's credentials are supplied via env vars
on the setup call. Import is always safe; nothing here touches the network at
import time.
"""
from . import config, delivery  # noqa: F401
