"""
Type stubs for the `decky` module injected into the plugin's Python runtime by
Decky Loader. These are not used at runtime — they exist so editors/type checkers
understand the globals and helpers Decky provides. See:
https://wiki.deckbrew.xyz/
"""

from typing import Any
from logging import Logger

# --- Environment / path constants -------------------------------------------
HOME: str
USER: str
DECKY_VERSION: str
DECKY_USER: str
DECKY_USER_HOME: str
DECKY_HOME: str
DECKY_PLUGIN_SETTINGS_DIR: str
DECKY_PLUGIN_RUNTIME_DIR: str
DECKY_PLUGIN_LOG_DIR: str
DECKY_PLUGIN_DIR: str
DECKY_PLUGIN_NAME: str
DECKY_PLUGIN_VERSION: str
DECKY_PLUGIN_AUTHOR: str

# --- Logging -----------------------------------------------------------------
logger: Logger

# --- Event bus (backend -> frontend) ----------------------------------------
async def emit(event: str, *args: Any) -> None: ...

# --- Settings helpers --------------------------------------------------------
def migrate_any(target_dir: str, *files: str) -> dict[str, str]: ...
def migrate_settings(*files: str) -> dict[str, str]: ...
def migrate_runtime(*files: str) -> dict[str, str]: ...
def migrate_logs(*files: str) -> dict[str, str]: ...
