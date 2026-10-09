import os
import random
import asyncio
from typing import Optional
from playwright.async_api import async_playwright, BrowserContext, Page, Error as PlaywrightError

try:
    from playwright._impl._errors import TargetClosedError
except ImportError:
    TargetClosedError = PlaywrightError

try:
    from playwright_stealth.stealth import stealth_async
except ImportError:
    try:
        from playwright_stealth import stealth_async
    except ImportError:
        async def stealth_async(page: Page) -> None:
            await page.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                """
            )


def is_browser_disconnected_error(e: Exception) -> bool:
    """Checks if an exception was caused by a sudden browser crash, disconnect, or OS sleep/wake."""
    if isinstance(e, (PlaywrightError, TargetClosedError)):
        msg = str(e).lower()
        if any(term in msg for term in [
            "target closed",
            "target page, context or browser has been closed",
            "browser has been closed",
            "connection closed",
            "page closed",
            "session closed",
            "browser closed",
            "broken pipe",
        ]):
            return True
    return False


class StealthBrowserTool:
    def __init__(self, headless: bool = False, user_data_dir: str = "data/browser_profile"):
        self.headless = headless
        self.user_data_dir = os.path.abspath(user_data_dir)
        os.makedirs(self.user_data_dir, exist_ok=True)
        self.playwright = None
        self.context: Optional[BrowserContext] = None

    def cleanup_stale_locks(self) -> None:
        """Removes stale Chromium Singleton lock files left behind by an ungraceful OS sleep or termination."""
        lock_files = ["SingletonLock", "SingletonCookie", "SingletonSocket"]
        for lock_name in lock_files:
            lock_path = os.path.join(self.user_data_dir, lock_name)
            try:
                if os.path.islink(lock_path) or os.path.exists(lock_path):
                    os.unlink(lock_path)
            except OSError:
                pass

    async def initialize(self) -> None:
        self.cleanup_stale_locks()
        self.playwright = await async_playwright().start()
        try:
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=self.headless,
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-infobars",
                    "--start-maximized",
                ],
            )
        except (PlaywrightError, TargetClosedError):
            self.cleanup_stale_locks()
            raise

    async def get_page(self, url: str) -> Page:
        try:
            if not self.context or not self.context.pages:
                page = await self.context.new_page()
            else:
                page = self.context.pages[0]

            await stealth_async(page)
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            await self._human_delay(1.5, 2.5)
            return page
        except (PlaywrightError, TargetClosedError):
            raise

    async def _human_delay(self, min_s: float = 1.0, max_s: float = 2.0) -> None:
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def upload_master_pdf(self, page: Page, pdf_path: str) -> bool:
        absolute_pdf_path = os.path.abspath(pdf_path)
        if not os.path.exists(absolute_pdf_path):
            raise FileNotFoundError(f"Resume PDF not found at {absolute_pdf_path}")

        file_selectors = [
            'input[type="file"]',
            'input[name="file"]',
            'input[id*="file"]',
            'input[id*="resume"]',
            'input[data-qa="resume-upload"]',
        ]

        for selector in file_selectors:
            elements = await page.query_selector_all(selector)
            for el in elements:
                try:
                    await el.set_input_files(absolute_pdf_path)
                    await self._human_delay(1.0, 2.0)
                    return True
                except Exception:
                    continue

        return False

    async def fill_input_field(self, page: Page, selector: str, value: str) -> None:
        try:
            el = await page.wait_for_selector(selector, state="visible", timeout=2500)
            if el:
                await el.click()
                await self._human_delay(0.1, 0.2)
                await el.fill("")
                await page.keyboard.type(str(value), delay=random.randint(15, 40))
        except Exception:
            pass

    async def take_review_screenshot(self, page: Page, job_id: str) -> str:
        os.makedirs("data/screenshots", exist_ok=True)
        screenshot_path = os.path.abspath(f"data/screenshots/{job_id}_review.png")
        await page.screenshot(path=screenshot_path, full_page=True)
        return screenshot_path

    async def close(self) -> None:
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        finally:
            self.context = None
        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception:
            pass
        finally:
            self.playwright = None
        self.cleanup_stale_locks()