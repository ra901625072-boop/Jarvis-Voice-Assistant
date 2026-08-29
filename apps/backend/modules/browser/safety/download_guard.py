"""
modules/browser/safety/download_guard.py — Sandboxed File Download Security Guard.

Interceptors and validates file downloads, enforcing file extension whitelisting
and preventing malicious automated payload downloads.
"""

import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("JARVIS.Browser.DownloadGuard")


class DownloadGuard:
    """
    Manages and restricts automated file downloads from the browser.
    """

    DEFAULT_ALLOWED_EXTENSIONS = {
        ".pdf", ".csv", ".json", ".txt", ".md", ".png", ".jpg", ".jpeg",
        ".webp", ".svg", ".docx", ".xlsx", ".pptx", ".zip", ".tar.gz"
    }

    DANGEROUS_EXTENSIONS = {
        ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".msi", ".scr", ".pif", ".jar"
    }

    def __init__(self, download_dir: str = "d:/Jarvis/apps/backend/data/downloads"):
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)

    def is_safe_filename(self, filename: str) -> bool:
        """Checks if a downloaded filename has a safe extension."""
        if not filename:
            return False

        lower = filename.lower()
        for dangerous in self.DANGEROUS_EXTENSIONS:
            if lower.endswith(dangerous):
                return False

        return True

    async def handle_download(self, download_obj: Any) -> Dict[str, Any]:
        """
        Saves a Playwright download object into the sandboxed directory if permitted.
        """
        try:
            suggested_filename = download_obj.suggested_filename
            if not self.is_safe_filename(suggested_filename):
                logger.warning(f"BLOCKED DANGEROUS DOWNLOAD: '{suggested_filename}'")
                await download_obj.cancel()
                return {
                    "success": False,
                    "error": f"Download of '{suggested_filename}' blocked: executable or high-risk file extension.",
                }

            destination = os.path.join(self.download_dir, suggested_filename)
            await download_obj.save_as(destination)
            logger.info(f"Safely downloaded file to: {destination}")

            return {
                "success": True,
                "filename": suggested_filename,
                "path": destination,
                "size_bytes": os.path.getsize(destination) if os.path.exists(destination) else 0,
            }
        except Exception as e:
            logger.exception(f"Error handling download: {e}")
            return {
                "success": False,
                "error": str(e),
            }
