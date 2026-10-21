"""Notificaciones de escritorio en modo local. Implementa REM-08.

`notify-send` sobre el D-Bus de la sesión del usuario (el servicio corre con
`systemd --user`). Sin shell: argumentos literales. El cuerpo se escapa
porque los daemons (mako, dunst) interpretan markup.
"""

import asyncio
import html
import logging
import shutil

logger = logging.getLogger(__name__)

APP_NAME = "Finanzas"
TIMEOUT_SECONDS = 10


def is_available() -> bool:
    return shutil.which("notify-send") is not None


async def notify(message: str, title: str = APP_NAME) -> bool:
    """Show one notification; True when notify-send exited cleanly."""
    executable = shutil.which("notify-send")
    if executable is None:
        return False
    try:
        process = await asyncio.create_subprocess_exec(
            executable,
            f"--app-name={APP_NAME}",
            "--urgency=normal",
            "--",
            title,
            html.escape(message, quote=False),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        logger.exception("desktop notification failed")
        return False
    try:
        code = await asyncio.wait_for(process.wait(), TIMEOUT_SECONDS)
    except TimeoutError:
        process.kill()
        logger.warning("desktop notification timed out")
        return False
    return code == 0
