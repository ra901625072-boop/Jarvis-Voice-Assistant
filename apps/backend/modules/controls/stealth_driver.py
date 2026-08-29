"""
stealth_driver.py — Humanized Browser Interaction & Anti-Detection Utilities.

Simulates natural human-like keystroke delays, cursor micro-pauses, and smooth
interactions for Playwright browser automation on WhatsApp, Instagram, and LinkedIn.
"""
import asyncio
import random
import logging
from typing import Optional, Any

logger = logging.getLogger("JARVIS.StealthDriver")


class StealthDriver:
    """
    Provides human-like interaction primitives for Playwright Page instances.
    """

    @staticmethod
    async def type_human_like(
        page: Any,
        selector: str,
        text: str,
        min_delay_ms: int = 40,
        max_delay_ms: int = 110,
        clear_first: bool = False
    ) -> bool:
        """
        Types text character-by-character with randomized human typing jitter,
        incorporating natural pauses at punctuation and word boundaries.
        """
        try:
            if not page or not text:
                return False

            element = await page.wait_for_selector(selector, timeout=8000)
            if not element:
                return False

            await element.click()
            await asyncio.sleep(random.uniform(0.1, 0.25))

            if clear_first:
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await asyncio.sleep(0.1)

            for char in text:
                # Type the character
                await page.keyboard.type(char)

                # Base randomized delay per keystroke
                delay = random.uniform(min_delay_ms / 1000.0, max_delay_ms / 1000.0)

                # Natural cognitive pauses at spaces and punctuation
                if char in (" ", "\n"):
                    delay += random.uniform(0.08, 0.18)
                elif char in (".", ",", "!", "?", ":", ";"):
                    delay += random.uniform(0.15, 0.30)

                await asyncio.sleep(delay)

            await asyncio.sleep(random.uniform(0.15, 0.35))
            return True
        except Exception as e:
            logger.debug(f"Stealth typing fallback to fill due to: {e}")
            try:
                await page.fill(selector, text)
                return True
            except Exception as fill_err:
                logger.error(f"Failed typing into selector '{selector}': {fill_err}")
                return False

    @staticmethod
    async def click_human_like(
        page: Any,
        selector: str,
        hover_first: bool = True,
        timeout: int = 8000
    ) -> bool:
        """
        Hovers over an element with a natural micro-delay before clicking.
        """
        try:
            if not page:
                return False

            element = await page.wait_for_selector(selector, timeout=timeout)
            if not element:
                return False

            if hover_first:
                try:
                    await element.hover()
                    await asyncio.sleep(random.uniform(0.12, 0.28))
                except Exception:
                    pass

            await element.click()
            await asyncio.sleep(random.uniform(0.1, 0.25))
            return True
        except Exception as e:
            logger.debug(f"Stealth click fallback: {e}")
            try:
                await page.click(selector)
                return True
            except Exception as click_err:
                logger.error(f"Failed clicking selector '{selector}': {click_err}")
                return False

    @staticmethod
    async def smooth_scroll(page: Any, distance: int = 400, steps: int = 5) -> None:
        """
        Scrolls smoothly in incremental chunks rather than an instant jump.
        """
        try:
            if not page:
                return
            step_distance = distance / steps
            for _ in range(steps):
                await page.mouse.wheel(0, step_distance)
                await asyncio.sleep(random.uniform(0.05, 0.12))
        except Exception as e:
            logger.debug(f"Smooth scroll exception: {e}")
