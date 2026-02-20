"""
Naver Cafe Scraper Module
Handles login, article list retrieval, and content extraction using Playwright.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

from playwright.async_api import async_playwright, Page, Frame, BrowserContext

logger = logging.getLogger(__name__)


@dataclass
class CafePost:
    """Represents a single Naver Cafe post."""
    id: int
    title: str
    content: str
    url: str
    date: str = ""
    author: str = ""


class NaverLoginError(Exception):
    """Raised when Naver login fails."""
    pass


class ClubIdResolutionError(Exception):
    """Raised when numeric club ID cannot be extracted from the cafe page."""
    pass


class NaverCafeScraper:
    """
    Scrapes posts from a Naver Cafe board.

    Accepts the human-readable cafe URL name (e.g. "daechi2dongchurch")
    instead of the internal numeric club ID. The numeric ID is resolved
    automatically at runtime by inspecting the cafe's main page.

    Authentication options (use ONE of the two):
      A. Cookie-based (recommended for CI/automation):
           Set naver_cookies="NID_AUT=xxx;NID_SES=yyy;NID_JKL=zzz"
           How to get cookies: log in to naver.com in Chrome, open
           DevTools → Application → Cookies → .naver.com, copy the values.
      B. ID/PW login:
           Set naver_id and naver_pw. Works locally for first-time setup,
           but Naver's device-confirmation flow blocks headless logins on
           new machines (e.g. every fresh GitHub Actions runner).

    Usage:
        # Cookie auth (recommended)
        scraper = NaverCafeScraper(naver_cookies="NID_AUT=xxx;NID_SES=yyy")
        # ID/PW auth (local testing only)
        scraper = NaverCafeScraper(naver_id="myid", naver_pw="mypassword")

        posts = scraper.get_new_posts(
            cafe_url_name="daechi2dongchurch",
            board_id="123",
            last_id=0,
        )
    """

    LOGIN_URL = "https://nid.naver.com/nidlogin.login"
    CAFE_MAIN_URL = "https://cafe.naver.com/{cafe_url_name}"

    # Article list still requires the internal numeric club_id (Naver API constraint).
    # This is resolved automatically via _resolve_club_id().
    ARTICLE_LIST_URL = (
        "https://cafe.naver.com/ArticleList.nhn"
        "?search.clubid={club_id}"
        "&search.menuid={board_id}"
        "&userDisplay=50"
        "&search.page=1"
    )

    # Article reading uses the clean name-based URL — no numeric ID needed.
    ARTICLE_READ_URL = "https://cafe.naver.com/{cafe_url_name}/{article_id}"

    # Selectors to try for article title (in priority order)
    TITLE_SELECTORS = [
        ".title_text",
        "h3.title",
        ".ArticleTitle",
        ".tit-article",
        ".article-head .title",
        "h2.title",
    ]

    # Selectors to try for article body content
    CONTENT_SELECTORS = [
        ".se-main-container",        # Smart Editor 3 (newest)
        ".se-module-text",           # Smart Editor 3 text block
        "#tbody",                    # Old editor
        ".ArticleContentBox .tbody",
        ".article_body",
        ".article-body",
        ".ContentRenderer",
    ]

    DATE_SELECTORS = [".date", ".article_date", "span.date", ".se-date"]
    AUTHOR_SELECTORS = [".nick", ".m-tcol-c", ".nickname", ".writer_info .nick"]

    def __init__(
        self,
        naver_id: str = "",
        naver_pw: str = "",
        naver_cookies: str = "",
    ):
        self.naver_id = naver_id
        self.naver_pw = naver_pw
        self.naver_cookies = naver_cookies  # "NID_AUT=xxx;NID_SES=yyy;NID_JKL=zzz"

    def get_new_posts(
        self,
        cafe_url_name: str,
        board_id: str,
        last_id: int,
        max_posts: int = 20,
    ) -> list[CafePost]:
        """
        Synchronous entry point. Returns new posts with ID > last_id.

        Args:
            cafe_url_name: Text-based cafe identifier (e.g. "daechi2dongchurch").
            board_id:      Numeric board (menu) ID — found in the board's URL.
            last_id:       Last processed article ID; only newer posts are returned.
            max_posts:     Safety cap on number of posts to process per run.

        Returns:
            List of CafePost objects sorted by article ID (oldest first).
        """
        return asyncio.run(
            self._run(cafe_url_name, board_id, last_id, max_posts)
        )

    # ------------------------------------------------------------------
    # Internal async implementation
    # ------------------------------------------------------------------

    async def _run(
        self,
        cafe_url_name: str,
        board_id: str,
        last_id: int,
        max_posts: int,
    ) -> list[CafePost]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="ko-KR",
                viewport={"width": 1280, "height": 800},
            )
            # Hide webdriver fingerprint so Naver doesn't detect headless Chrome
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            try:
                page = await context.new_page()

                if self.naver_cookies:
                    await self._inject_cookies(context)
                    logger.info("Using cookie-based auth (skipping login form).")
                else:
                    await self._login(page)

                # Resolve the internal numeric club_id once per session
                club_id = await self._resolve_club_id(page, cafe_url_name)
                logger.info("Resolved club_id=%s for '%s'", club_id, cafe_url_name)

                posts = await self._fetch_new_posts(
                    page, cafe_url_name, club_id, board_id, last_id, max_posts
                )
                return posts
            finally:
                await browser.close()

    async def _inject_cookies(self, context: BrowserContext) -> None:
        """
        Inject pre-authenticated Naver session cookies into the browser context.

        Cookie format: "NID_AUT=xxx;NID_SES=yyy;NID_JKL=zzz"
        Obtain by logging in to naver.com in Chrome and copying cookie values from
        DevTools -> Application -> Cookies -> .naver.com
        """
        cookies = []
        for pair in self.naver_cookies.split(";"):
            pair = pair.strip()
            if "=" in pair:
                name, _, value = pair.partition("=")
                cookies.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": ".naver.com",
                    "path": "/",
                })
        if not cookies:
            raise NaverLoginError("NAVER_COOKIES is set but contains no valid key=value pairs.")
        await context.add_cookies(cookies)
        logger.info("Injected %d session cookie(s).", len(cookies))

    async def _login(self, page: Page) -> None:
        """Log in to Naver. Raises NaverLoginError on failure."""
        logger.info("Navigating to Naver login page...")
        await page.goto(self.LOGIN_URL, wait_until="networkidle", timeout=30_000)

        # Wait for the form fields to be visible
        await page.wait_for_selector("#id", state="visible", timeout=15_000)

        # Use type() with delays to simulate realistic keystrokes
        # (fill() bypasses JS input events that Naver's form relies on)
        await page.click("#id")
        await page.type("#id", self.naver_id, delay=80)
        await page.click("#pw")
        await page.type("#pw", self.naver_pw, delay=80)

        # Try multiple possible button selectors in priority order
        submitted = False
        for selector in [".btn_login", "button[type=submit]", "#btnSubmit", "input[type=submit]"]:
            try:
                btn = await page.query_selector(selector)
                if btn:
                    await btn.click()
                    submitted = True
                    logger.debug("Clicked login button via selector: %s", selector)
                    break
            except Exception:
                continue
        if not submitted:
            await page.keyboard.press("Enter")

        # Wait for the page to navigate away from the login form
        try:
            await page.wait_for_function(
                "window.location.href.indexOf('nidlogin.login') === -1",
                timeout=12_000,
            )
        except Exception:
            pass  # Timeout is OK - we'll inspect the URL next

        await page.wait_for_load_state("networkidle", timeout=10_000)
        current_url = page.url
        logger.info("Post-login URL: %s", current_url)

        # --- Device confirmation required (new device / headless browser) ---
        if "deviceConfirm" in current_url or "device_confirm" in current_url:
            await page.screenshot(path="login_device_confirm.png", full_page=True)
            raise NaverLoginError(
                "Naver requires device confirmation for this new login.\n"
                "ID/PW login cannot be automated on new machines (e.g. GitHub Actions).\n\n"
                "Use cookie-based auth instead:\n"
                "  1. Log in to naver.com in Chrome on your computer\n"
                "  2. Open DevTools (F12) -> Application -> Cookies -> .naver.com\n"
                "  3. Copy the values of: NID_AUT, NID_SES, NID_JKL\n"
                "  4. Set env var NAVER_COOKIES=NID_AUT=<val>;NID_SES=<val>;NID_JKL=<val>\n"
                "  5. Remove NAVER_ID and NAVER_PW from your config\n"
                "Screenshot saved to login_device_confirm.png"
            )

        # --- Still on login page = wrong credentials ---
        if "nidlogin" in current_url:
            await page.screenshot(path="login_failed.png", full_page=True)
            err = ""
            for sel in [".login_error", ".error_message", "#err_common"]:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        err = (await el.text_content() or "").strip()
                        break
                except Exception:
                    continue
            raise NaverLoginError(
                f"Naver login failed (wrong credentials?): {err or 'check login_failed.png'}"
            )

        # Handle optional "keep login state" popup
        try:
            btn = await page.wait_for_selector("#new\\.save", timeout=3_000)
            if btn:
                await btn.click()
                await page.wait_for_load_state("networkidle", timeout=10_000)
        except Exception:
            pass

        logger.info("Naver login successful (URL: %s)", page.url)

    async def _resolve_club_id(self, page: Page, cafe_url_name: str) -> str:
        """
        Extract the internal numeric club ID from the cafe's main page.

        Naver's article list API requires a numeric club_id even when the
        cafe is accessed via a text-based URL. This method resolves it by
        inspecting the iframe src and page source of the cafe's main page.

        Raises ClubIdResolutionError if the ID cannot be found.
        """
        url = self.CAFE_MAIN_URL.format(cafe_url_name=cafe_url_name)
        logger.info("Resolving club_id from %s", url)
        await page.goto(url, wait_until="networkidle", timeout=30_000)

        # Strategy 1: extract from the cafe_main iframe src attribute
        iframe_el = await page.query_selector("#cafe_main")
        if iframe_el:
            src = await iframe_el.get_attribute("src") or ""
            m = re.search(r"clubid=(\d+)", src, re.IGNORECASE)
            if m:
                return m.group(1)

        # Strategy 2: search the raw page HTML for known patterns
        html = await page.content()
        for pattern in (
            r"clubid=(\d+)",
            r'"clubId"\s*:\s*"?(\d+)"?',
            r"g_sClubid\s*=\s*[\"'](\d+)[\"']",
            r"search\.clubid=(\d+)",
        ):
            m = re.search(pattern, html, re.IGNORECASE)
            if m:
                return m.group(1)

        raise ClubIdResolutionError(
            f"Could not resolve numeric club_id for '{cafe_url_name}'. "
            "Check that the cafe URL name is correct and the account has access."
        )

    async def _fetch_new_posts(
        self,
        page: Page,
        cafe_url_name: str,
        club_id: str,
        board_id: str,
        last_id: int,
        max_posts: int,
    ) -> list[CafePost]:
        """Get all articles newer than last_id from the target board."""
        article_ids = await self._list_article_ids(page, cafe_url_name, club_id, board_id)

        new_ids = sorted(aid for aid in article_ids if aid > last_id)
        if not new_ids:
            logger.info("No new articles found (last_id=%d).", last_id)
            return []

        if len(new_ids) > max_posts:
            logger.warning("Found %d new articles; capping at %d.", len(new_ids), max_posts)
            new_ids = new_ids[-max_posts:]

        logger.info("Processing %d new article(s): %s", len(new_ids), new_ids)

        posts: list[CafePost] = []
        for aid in new_ids:
            post = await self._fetch_post(page, cafe_url_name, aid)
            if post:
                posts.append(post)

        return posts

    async def _list_article_ids(
        self, page: Page, cafe_url_name: str, club_id: str, board_id: str
    ) -> list[int]:
        """
        Navigate to the target board and return all visible article IDs.

        Handles two Naver Cafe URL formats for article links:
          - Legacy:  /ArticleRead.nhn?clubid=X&articleid=Y
          - Modern:  /cafename/Y  (used in the ca-fe redesigned UI)
        """
        # Use the full cafe page URL with iframe_url param so the board
        # loads properly inside the cafe shell (more reliable than direct ArticleList.nhn)
        board_url = (
            f"https://cafe.naver.com/{cafe_url_name}"
            f"?iframe_url=/ArticleList.nhn"
            f"%3Fsearch.clubid%3D{club_id}"
            f"%26search.menuid%3D{board_id}"
            f"%26userDisplay%3D50"
        )
        logger.info("Fetching board: %s", board_url)
        await page.goto(board_url, wait_until="networkidle", timeout=30_000)

        # Wait for the cafe_main iframe to appear
        try:
            await page.wait_for_selector("#cafe_main", state="attached", timeout=10_000)
        except Exception:
            logger.warning("cafe_main iframe did not appear; falling back to page content.")

        frame = page.frame(name="cafe_main")
        target: Page | Frame = frame if frame else page

        # Give the iframe content time to fully render
        await target.wait_for_load_state("domcontentloaded")

        all_links = await target.query_selector_all("a")
        logger.debug("Total <a> elements in board: %d", len(all_links))

        ids: set[int] = set()
        for link in all_links:
            href = await link.get_attribute("href") or ""

            # Pattern 1 — legacy: ?articleid=12345 or &articleid=12345
            m = re.search(r"[?&]articleid=(\d+)", href)
            if m:
                ids.add(int(m.group(1)))
                continue

            # Pattern 2 — modern ca-fe: /daechi2dongchurch/12345
            m = re.search(rf"/{re.escape(cafe_url_name)}/(\d+)(?:[?#]|$)", href)
            if m:
                ids.add(int(m.group(1)))

        logger.info("Found %d article ID(s) in board.", len(ids))
        return list(ids)

    async def _fetch_post(
        self, page: Page, cafe_url_name: str, article_id: int
    ) -> Optional[CafePost]:
        """Navigate to an article and extract its content."""
        url = self.ARTICLE_READ_URL.format(
            cafe_url_name=cafe_url_name, article_id=article_id
        )
        try:
            await page.goto(url, wait_until="networkidle", timeout=30_000)

            frame = page.frame(name="cafe_main")
            target: Page | Frame = frame if frame else page

            title = await self._extract_text(target, self.TITLE_SELECTORS)
            content = await self._extract_text(target, self.CONTENT_SELECTORS, inner_text=True)
            date = await self._extract_text(target, self.DATE_SELECTORS)
            author = await self._extract_text(target, self.AUTHOR_SELECTORS)

            if not title and not content:
                logger.warning("No content extracted for article %d; skipping.", article_id)
                return None

            logger.info("Extracted article %d: %s", article_id, title[:60])
            return CafePost(
                id=article_id,
                title=title,
                content=content,
                url=url,
                date=date,
                author=author,
            )
        except Exception as exc:
            logger.error("Error fetching article %d: %s", article_id, exc)
            return None

    @staticmethod
    async def _extract_text(
        target,
        selectors: list[str],
        inner_text: bool = False,
    ) -> str:
        """Try each selector in order and return the first non-empty match."""
        for sel in selectors:
            try:
                el = await target.query_selector(sel)
                if el:
                    text = (
                        await el.inner_text() if inner_text
                        else await el.text_content()
                    )
                    stripped = (text or "").strip()
                    if stripped:
                        return stripped
            except Exception:
                continue
        return ""
