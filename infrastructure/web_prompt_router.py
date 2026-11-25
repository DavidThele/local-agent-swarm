import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from google.genai import types
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)

from infrastructure.logging import log
from infrastructure.models import GEMINI_4_HYDROGEN, get_aistudio_name
from runtime import (
    AISTUDIO_CDP_HOST as DEFAULT_CDP_HOST,
    AISTUDIO_CDP_PORT as DEFAULT_CDP_PORT,
    AISTUDIO_CHROME_PROFILE as DEFAULT_PROFILE_DIR,
    AISTUDIO_CLOSE_DELAY_SECONDS as DEFAULT_CLOSE_DELAY_SECONDS,
    CHROME_APP_PATH,
    CHROME_BINARY,
    WEB_ROUTER_RESPONSE_TIMEOUT_SECONDS,
)

# Sets textarea value directly via the native setter and fires Angular input/change
# events without waiting on requestAnimationFrame (which Chrome pauses in background tabs).
SET_TEXTAREA_VALUE_JS = """
(el, text) => {
    el.focus();
    const proto = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
    if (proto && proto.set) {
        proto.set.call(el, text);
    } else {
        el.value = text;
    }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
}
"""

# Selectors grounded in AI Studio's Angular Material DOM
SEL_PROMPT_TEXTAREA = 'ms-prompt-box textarea[formcontrolname="promptText"]'
SEL_RUN_BUTTON = "ms-run-button button"
SEL_RUN_BUTTON_LABEL = "ms-run-button .run-button-label"
SEL_THINKING_SELECT = 'mat-select[aria-label="Thinking Level"]'
SEL_THINKING_VALUE = 'mat-select[aria-label="Thinking Level"] .mat-mdc-select-min-line'
SEL_OVERLAY_OPTIONS = '[role="listbox"] [role="option"], mat-option'
SEL_MODEL_TURNS = 'ms-chat-turn:has([data-turn-role="Model"])'
SEL_TOKEN_COUNT = ".v3-token-count-value"

# JS extractor that reconstructs clean text/markdown from a model <ms-chat-turn>
# while skipping thinking chunks and code-block header chrome (no clipboard mutation).
EXTRACT_MODEL_TURN_JS = """
(turnEl) => {
    if (!turnEl) return "";

    const contentRoot =
        turnEl.querySelector('[data-turn-role="Model"] .turn-content') ||
        turnEl.querySelector('.turn-content') ||
        turnEl;

    const SKIP_TAGS = new Set([
        'BUTTON', 'SVG', 'SCRIPT', 'STYLE', 'MAT-EXPANSION-PANEL-HEADER',
        'MS-CHAT-TURN-OPTIONS', 'MS-THOUGHT-CHUNK'
    ]);

    const BLOCK_TAGS = new Set([
        'P', 'DIV', 'LI', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
        'BLOCKQUOTE', 'TR', 'SECTION', 'ARTICLE'
    ]);

    const isThoughtNode = (el) => {
        if (!el || el.nodeType !== 1) return false;
        const tag = el.tagName.toUpperCase();
        if (tag.includes('THOUGHT')) return true;
        const cls = (el.className && typeof el.className === 'string') ? el.className.toLowerCase() : '';
        if (cls.includes('thought-chunk') || cls.includes('thought-container')) return true;
        if (el.querySelector && el.querySelector('ms-thought-chunk')) return true;
        return false;
    };

    const walk = (node) => {
        if (!node) return "";
        if (node.nodeType === 3) {
            return node.textContent || "";
        }
        if (node.nodeType !== 1) return "";

        const tag = node.tagName.toUpperCase();
        if (SKIP_TAGS.has(tag) || isThoughtNode(node)) return "";

        const cls = (node.className && typeof node.className === 'string') ? node.className : '';
        if (
            cls.includes('actions-container') ||
            cls.includes('turn-footer') ||
            cls.includes('turn-information') ||
            cls.includes('author-label') ||
            cls.includes('timestamp')
        ) {
            return "";
        }

        if (tag === 'BR') return "\\n";

        if (tag === 'MS-CODE-BLOCK') {
            const lang = (node.getAttribute('data-test-language') || '').trim();
            const codeEl =
                node.querySelector('.mat-expansion-panel-body code') ||
                node.querySelector('pre code') ||
                node.querySelector('code');
            const codeText = codeEl ? codeEl.innerText : '';
            const trimmed = codeText.replace(/\\n$/, '');
            return "\\n```" + lang + "\\n" + trimmed + "\\n```\\n";
        }

        if (tag === 'PRE') {
            const codeEl = node.querySelector('code');
            const text = (codeEl ? codeEl.innerText : node.innerText) || '';
            return "\\n```\\n" + text.replace(/\\n$/, '') + "\\n```\\n";
        }

        let out = "";
        for (const child of node.childNodes) {
            out += walk(child);
        }

        if (BLOCK_TAGS.has(tag) && out.trim().length > 0) {
            if (!out.endsWith("\\n")) out += "\\n";
        }
        return out;
    };

    const chunks = Array.from(contentRoot.querySelectorAll(':scope > ms-prompt-chunk'));
    let combined = "";
    if (chunks.length > 0) {
        const parts = [];
        for (const chunk of chunks) {
            if (isThoughtNode(chunk)) continue;
            const text = walk(chunk).trim();
            if (text) parts.push(text);
        }
        combined = parts.join("\\n\\n");
    } else {
        combined = walk(contentRoot);
    }

    return combined.replace(/\\n{3,}/g, "\\n\\n").trim();
}
"""

THINKING_LEVEL_ALIASES = {
    "low": "Low",
    "medium": "Medium",
    "med": "Medium",
    "high": "High",
    "extra_high": "Extra High",
    "extra-high": "Extra High",
    "extra high": "Extra High",
    "extrahigh": "Extra High",
    "minimal": "Minimal",
    "off": "Off",
    "none": "Off",
}

_CHAT_ID_RE = re.compile(r"/prompts/([^/?#]+)")


def _normalize_thinking_level(level: str | None) -> str | None:
    if not level:
        return None
    cleaned = level.strip()
    if not cleaned:
        return None
    return THINKING_LEVEL_ALIASES.get(cleaned.lower(), cleaned)


def _extract_chat_id(url: str) -> str | None:
    match = _CHAT_ID_RE.search(url or "")
    if not match:
        return None
    candidate = match.group(1)
    if candidate == "new_chat":
        return None
    return candidate


@dataclass
class _ChatSession:
    page: Page | None = None
    chat_id: str | None = None
    chat_url: str | None = None
    model: str = GEMINI_4_HYDROGEN
    thinking_level: str | None = None


class WebPromptRouter:
    """
    Routes prompts through Google AI Studio (https://aistudio.google.com/prompts/new_chat)
    using Playwright over CDP connected to a dedicated headed Chrome profile.

    Safe for concurrent multi-agent threads: Playwright's async API runs on a single
    dedicated background event-loop thread, while each conversation owns its own tab
    and tracks its AI Studio chat ID for persistence across turns.
    """

    def __init__(
        self,
        profile_dir: str = DEFAULT_PROFILE_DIR,
        cdp_port: int = DEFAULT_CDP_PORT,
        response_timeout_seconds: float = WEB_ROUTER_RESPONSE_TIMEOUT_SECONDS,
    ):
        self.profile_dir = os.path.expanduser(profile_dir)
        self.cdp_port = cdp_port
        self.response_timeout_seconds = response_timeout_seconds

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._loop_init_lock = threading.Lock()

        # Owned exclusively by self._loop
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._browser_lock: asyncio.Lock | None = None
        self._tab_open_lock: asyncio.Lock | None = None

        # Maps id(chat_history) -> _ChatSession, and chat_id -> _ChatSession
        self._sessions_by_history_id: dict[int, _ChatSession] = {}
        self._sessions_by_chat_id: dict[str, _ChatSession] = {}

    def _ensure_event_loop(self) -> asyncio.AbstractEventLoop:
        with self._loop_init_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop

            ready = threading.Event()
            loop_holder: list[asyncio.AbstractEventLoop] = []

            def _runner():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._browser_lock = asyncio.Lock()
                self._tab_open_lock = asyncio.Lock()
                loop_holder.append(loop)
                ready.set()
                loop.run_forever()

            thread = threading.Thread(target=_runner, name="WebPromptRouterLoop", daemon=True)
            thread.start()
            ready.wait()
            self._loop = loop_holder[0]
            self._loop_thread = thread
            return self._loop

    def _cdp_base_url(self) -> str:
        return f"http://{DEFAULT_CDP_HOST}:{self.cdp_port}"

    def _cdp_version_url(self) -> str:
        return f"{self._cdp_base_url()}/json/version"

    def _is_cdp_listening(self) -> bool:
        try:
            with urllib.request.urlopen(self._cdp_version_url(), timeout=1):
                return True
        except (urllib.error.URLError, TimeoutError, OSError):
            return False

    def _launch_chrome_if_needed(self) -> None:
        if self._is_cdp_listening():
            return

        log(
            f"[WebRouter] Launching headed Chrome in background on port {self.cdp_port} "
            f"with profile {self.profile_dir}...",
            "info",
        )
        os.makedirs(self.profile_dir, exist_ok=True)
        chrome_args = [
            f"--remote-debugging-port={self.cdp_port}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "about:blank",
        ]
        if sys.platform == "darwin" and os.path.exists(CHROME_APP_PATH):
            # -g launches in the background without stealing focus; -n starts a separate instance
            cmd = ["open", "-g", "-n", "-a", CHROME_APP_PATH, "--args", *chrome_args]
        else:
            cmd = [CHROME_BINARY, *chrome_args]

        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        for _ in range(40):
            if self._is_cdp_listening():
                time.sleep(0.5)
                log("[WebRouter] Chrome CDP endpoint is ready.", "success")
                return
            time.sleep(0.5)

        raise RuntimeError(
            f"Timed out waiting for Chrome to open debugging port {self.cdp_port}."
        )

    async def _ensure_browser_context(self) -> BrowserContext:
        assert self._browser_lock is not None
        async with self._browser_lock:
            if self._browser is not None and self._browser.is_connected() and self._context is not None:
                # Ensure at least one window/page exists
                if not self._context.pages:
                    log("[WebRouter] No Chrome window/tab open; creating a new window...", "info")
                    await self._context.new_page()
                return self._context

            # Clean up stale handles if Chrome was closed externally
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
                self._browser = None
                self._context = None

            await asyncio.to_thread(self._launch_chrome_if_needed)

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.connect_over_cdp(
                self._cdp_base_url()
            )
            self._context = (
                self._browser.contexts[0]
                if self._browser.contexts
                else await self._browser.new_context()
            )
            if not self._context.pages:
                log("[WebRouter] No Chrome window detected; opening a new window...", "info")
                await self._context.new_page()

            return self._context

    async def _create_background_tab(self, context: BrowserContext, url: str = "about:blank") -> Page:
        """
        Opens a tab via CDP Target.createTarget(..., background=True) so Chrome
        never activates the tab or steals macOS window focus.
        """
        assert self._tab_open_lock is not None
        async with self._tab_open_lock:
            if not context.pages:
                await context.new_page()

            if self._browser is not None and self._browser.is_connected():
                before_ids = {id(p) for p in context.pages}
                try:
                    cdp = await self._browser.new_browser_cdp_session()
                    try:
                        await cdp.send(
                            "Target.createTarget",
                            {"url": url, "background": True},
                        )
                    finally:
                        await cdp.detach()

                    for _ in range(60):
                        for p in context.pages:
                            if id(p) not in before_ids:
                                return p
                        await asyncio.sleep(0.05)
                    log(
                        "[WebRouter] Background CDP tab did not attach in time; falling back to context.new_page().",
                        "warning",
                    )
                except Exception as exc:
                    log(
                        f"[WebRouter] Background CDP tab creation failed ({exc}); falling back to context.new_page().",
                        "warning",
                    )

            return await context.new_page()

    async def _open_new_tab(self, context: BrowserContext) -> Page:
        # Always keep at least one anchor tab alive in the window so closing
        # agent tabs never closes the Chrome window (which would steal focus on recreate).
        return await self._create_background_tab(context, url="about:blank")

    async def _set_thinking_level(self, page: Page, thinking_level: str | None) -> None:
        target = _normalize_thinking_level(thinking_level)
        if not target:
            return

        select_loc = page.locator(SEL_THINKING_SELECT).first
        try:
            await select_loc.wait_for(state="visible", timeout=5000)
        except PlaywrightTimeoutError:
            log(
                f"[WebRouter] Thinking Level selector not visible on page; skipping '{target}'.",
                "warning",
            )
            return

        # Check current value first to avoid redundant clicks
        current_loc = page.locator(SEL_THINKING_VALUE).first
        if await current_loc.count() > 0:
            current_val = (await current_loc.inner_text()).strip()
            if current_val.lower() == target.lower():
                log(f"[WebRouter] Thinking level already set to '{current_val}'.", "debug")
                return

        await select_loc.evaluate("(el) => el.click()")

        # Angular Material renders options either inside a native popover listbox or
        # .cdk-overlay-container; get_by_role("option") matches visible accessible options
        # regardless of overlay container implementation.
        options_loc = page.get_by_role("option")
        try:
            await options_loc.first.wait_for(state="visible", timeout=5000)
        except PlaywrightTimeoutError:
            options_loc = page.locator(SEL_OVERLAY_OPTIONS)
            await options_loc.first.wait_for(state="visible", timeout=5000)

        option_count = await options_loc.count()
        available: list[str] = []
        matched = False
        for idx in range(option_count):
            opt = options_loc.nth(idx)
            opt_text = (await opt.inner_text()).strip()
            available.append(opt_text)
            if opt_text.lower() == target.lower():
                await opt.evaluate("(el) => el.click()")
                matched = True
                break

        if not matched:
            await page.keyboard.press("Escape")
            log(
                f"[WebRouter] Requested thinking level '{target}' not found in options {available}; "
                "leaving default.",
                "warning",
            )
            return

        # Wait briefly for the overlay menu to close
        try:
            await options_loc.first.wait_for(state="hidden", timeout=3000)
        except PlaywrightTimeoutError:
            pass
        log(f"[WebRouter] Set thinking level to '{target}'.", "debug")

    async def _get_or_create_session_page(
        self,
        *,
        history_key: int,
        model: str,
        thinking_level: str | None,
        chat_id: str | None,
        user: int = 0,
    ) -> tuple[_ChatSession, Page]:
        context = await self._ensure_browser_context()

        session = self._sessions_by_history_id.get(history_key)
        if session is None and chat_id:
            session = self._sessions_by_chat_id.get(chat_id)

        # Case 1: Existing session with a live tab
        if session is not None and session.page is not None and not session.page.is_closed():
            page = session.page
            # Refresh saved chat_id/url in case AI Studio updated the URL
            live_id = _extract_chat_id(page.url)
            if live_id:
                session.chat_id = live_id
                session.chat_url = page.url
                self._sessions_by_chat_id[live_id] = session
            return session, page

        # Case 2: Existing session whose tab was closed, or caller passed an existing chat_id
        resume_url = None
        if session is not None and session.chat_url:
            resume_url = session.chat_url
        elif chat_id:
            resume_url = f"https://aistudio.google.com/prompts/{chat_id}"

        if resume_url:
            log(f"[WebRouter] Reopening persistent chat tab: {resume_url}", "info")
            page = await self._open_new_tab(context)
            await page.goto(resume_url, wait_until="domcontentloaded", timeout=30000)
            await page.locator(SEL_PROMPT_TEXTAREA).first.wait_for(state="visible", timeout=30000)
            if session is None:
                session = _ChatSession(
                    page=page,
                    chat_id=chat_id or _extract_chat_id(page.url),
                    chat_url=page.url,
                    model=model,
                    thinking_level=thinking_level,
                )
            else:
                session.page = page
                session.chat_url = page.url
            self._sessions_by_history_id[history_key] = session
            if session.chat_id:
                self._sessions_by_chat_id[session.chat_id] = session
            return session, page

        # Case 3: Brand new chat tab
        aistudio_model = get_aistudio_name(model)
        encoded_model = urllib.parse.quote(aistudio_model, safe="")
        AISTUDIO_NEW_CHAT_URL = f"https://aistudio.google.com/u/{user}/prompts/new_chat"
        target_url = f"{AISTUDIO_NEW_CHAT_URL}?model={encoded_model}"

        log(
            f"[WebRouter] Opening new AI Studio chat tab (model={aistudio_model}, "
            f"thinking_level={thinking_level})...",
            "info",
        )
        page = await self._open_new_tab(context)
        await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        await page.locator(SEL_PROMPT_TEXTAREA).first.wait_for(state="visible", timeout=30000)

        await self._set_thinking_level(page, thinking_level)

        session = _ChatSession(
            page=page,
            chat_id=_extract_chat_id(page.url),
            chat_url=page.url if _extract_chat_id(page.url) else None,
            model=model,
            thinking_level=thinking_level,
        )
        self._sessions_by_history_id[history_key] = session
        return session, page

    async def _stop_generation(self, page: Page) -> None:
        try:
            run_btn = page.locator(SEL_RUN_BUTTON).first
            if await run_btn.count() > 0:
                aria_disabled = await run_btn.get_attribute("aria-disabled")
                if aria_disabled != "true":
                    await run_btn.click(timeout=2000)
        except Exception:
            pass

    async def _is_generating(self, page: Page) -> bool:
        try:
            label_loc = page.locator(SEL_RUN_BUTTON_LABEL).first
            if await label_loc.count() > 0:
                label_text = (await label_loc.inner_text()).strip().lower()
                if "stop" in label_text:
                    return True
            run_btn = page.locator(SEL_RUN_BUTTON).first
            if await run_btn.count() > 0:
                aria_label = (await run_btn.get_attribute("aria-label") or "").lower()
                if "stop" in aria_label:
                    return True
        except Exception:
            pass
        return False

    async def _read_token_count(self, page: Page) -> int:
        try:
            loc = page.locator(SEL_TOKEN_COUNT).first
            if await loc.count() > 0:
                raw = (await loc.inner_text()).replace(",", "")
                match = re.search(r"(\d+)", raw)
                if match:
                    return int(match.group(1))
        except Exception:
            pass
        return 0

    async def _send_prompt_async(
        self,
        *,
        prompt_text: str,
        model: str,
        history_key: int,
        thinking_level: str | None,
        chat_id: str | None,
        cancel_event: threading.Event | None,
        user: int = 0,
    ) -> tuple[str, int, str | None]:
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Prompt cancelled before dispatch.")

        session, page = await self._get_or_create_session_page(
            history_key=history_key,
            model=model,
            thinking_level=thinking_level,
            chat_id=chat_id,
            user=user,
        )

        try:
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Prompt cancelled before sending.")

            model_turns_loc = page.locator(SEL_MODEL_TURNS)
            prev_model_count = await model_turns_loc.count()

            textarea = page.locator(SEL_PROMPT_TEXTAREA).first
            await textarea.wait_for(state="visible", timeout=15000)
            await textarea.evaluate(SET_TEXTAREA_VALUE_JS, prompt_text)

            # Ensure Angular form control registers the filled value
            run_btn = page.locator(SEL_RUN_BUTTON).first
            for _ in range(20):
                aria_disabled = await run_btn.get_attribute("aria-disabled")
                if aria_disabled != "true":
                    break
                await textarea.evaluate(
                    "(el) => el.dispatchEvent(new Event('input', { bubbles: true }))"
                )
                await asyncio.sleep(0.1)

            aria_disabled = await run_btn.get_attribute("aria-disabled")
            if aria_disabled != "true":
                await run_btn.evaluate("(el) => el.click()")
            else:
                await textarea.press("Meta+Enter")

            deadline = time.monotonic() + self.response_timeout_seconds

            # Phase 1: Wait for a new model turn to appear
            while time.monotonic() < deadline:
                if cancel_event and cancel_event.is_set():
                    await self._stop_generation(page)
                    raise InterruptedError("Prompt cancelled while waiting for response.")

                current_count = await model_turns_loc.count()
                if current_count > prev_model_count:
                    break
                await asyncio.sleep(0.25)
            else:
                raise TimeoutError(
                    f"Timed out after {self.response_timeout_seconds}s waiting for AI Studio model turn."
                )

            # Phase 2: Wait for the final model turn to finish generating.
            # Note: AI Studio renders Thoughts as a separate <ms-chat-turn> with
            # data-turn-role="Model" BEFORE the final answer <ms-chat-turn>, and only
            # attaches the "Good response" feedback footer to the final answer turn.
            # Always poll the newest (last) model turn added after prev_model_count.
            last_text = ""
            stable_polls = 0
            latest_turn = model_turns_loc.last

            while time.monotonic() < deadline:
                if cancel_event and cancel_event.is_set():
                    await self._stop_generation(page)
                    raise InterruptedError("Prompt cancelled during generation.")

                # Capture the persistent chat ID as soon as AI Studio assigns it
                live_id = _extract_chat_id(page.url)
                if live_id and session.chat_id != live_id:
                    session.chat_id = live_id
                    session.chat_url = page.url
                    self._sessions_by_chat_id[live_id] = session
                    log(f"[WebRouter] Captured AI Studio chat ID: {live_id}", "debug")

                current_count = await model_turns_loc.count()
                if current_count > prev_model_count:
                    latest_turn = model_turns_loc.nth(current_count - 1)
                    footer_loc = latest_turn.locator('button[aria-label="Good response"]')
                    footer_visible = await footer_loc.count() > 0 and await footer_loc.first.is_visible()
                    still_generating = await self._is_generating(page)

                    if footer_visible and not still_generating:
                        current_text = await latest_turn.evaluate(EXTRACT_MODEL_TURN_JS)
                        if current_text == last_text:
                            stable_polls += 1
                            if stable_polls >= 2:
                                break
                        else:
                            last_text = current_text
                            stable_polls = 0

                await asyncio.sleep(0.3)
            else:
                raise TimeoutError(
                    f"Timed out after {self.response_timeout_seconds}s waiting for AI Studio generation to complete."
                )

            # Final chat ID capture check
            live_id = _extract_chat_id(page.url)
            if live_id:
                session.chat_id = live_id
                session.chat_url = page.url
                self._sessions_by_chat_id[live_id] = session

            response_text = await latest_turn.evaluate(EXTRACT_MODEL_TURN_JS)
            total_tokens = await self._read_token_count(page)
            return response_text, total_tokens, session.chat_id
        except BaseException:
            # Close the tab immediately on error or cancellation so failed sessions don't leak tabs.
            await self._close_session_async(history_key=history_key, chat_id=session.chat_id)
            raise

    async def _close_page_safely(self, page: Page | None) -> bool:
        if page is None:
            return False
        try:
            if page.is_closed():
                return False
            # Keep an anchor tab open so closing the last agent tab does not close the window.
            if self._context is not None:
                open_pages = [p for p in self._context.pages if not p.is_closed()]
                if len(open_pages) <= 1:
                    try:
                        await self._create_background_tab(self._context, url="about:blank")
                    except Exception:
                        pass
            await page.close()
            return True
        except Exception as exc:
            log(f"[WebRouter] Failed to close AI Studio tab: {exc}", "debug")
            return False

    async def _close_session_async(
        self,
        *,
        history_key: int | None = None,
        chat_id: str | None = None,
        delay_seconds: float = 0.0,
    ) -> bool:
        session = None
        if history_key is not None:
            session = self._sessions_by_history_id.pop(history_key, None)
        if session is None and chat_id:
            session = self._sessions_by_chat_id.pop(chat_id, None)
        elif session is not None and session.chat_id:
            self._sessions_by_chat_id.pop(session.chat_id, None)

        if session is None:
            return False

        page = session.page
        session.page = None
        saved_chat_id = session.chat_id

        if page is None:
            return False

        async def _finish_close() -> bool:
            if delay_seconds > 0:
                log(
                    f"[WebRouter] Waiting {delay_seconds:.1f}s for AI Studio autosave "
                    f"before closing tab (chat_id={saved_chat_id})...",
                    "debug",
                )
                await asyncio.sleep(delay_seconds)
            closed = await self._close_page_safely(page)
            if closed:
                log(
                    f"[WebRouter] Closed AI Studio tab for session (chat_id={saved_chat_id}).",
                    "debug",
                )
            return closed

        if delay_seconds > 0:
            # Schedule asynchronously on the router's event loop so workers return
            # immediately while AI Studio finishes autosaving in the background.
            asyncio.create_task(_finish_close())
            return True

        return await _finish_close()

    def close_session(
        self,
        chat_history=None,
        chat_id: str | None = None,
        delay_seconds: float | None = None,
    ) -> bool:
        """Closes the persistent AI Studio tab associated with a conversation/agent."""
        history_key = id(chat_history) if chat_history is not None else None
        if history_key is None and not chat_id:
            return False

        # Fast no-op when web router was never used (e.g. API backend or unit tests)
        if self._loop is None or not self._loop.is_running():
            return False
        if (
            (history_key is None or history_key not in self._sessions_by_history_id)
            and (not chat_id or chat_id not in self._sessions_by_chat_id)
        ):
            return False

        effective_delay = (
            DEFAULT_CLOSE_DELAY_SECONDS if delay_seconds is None else max(0.0, float(delay_seconds))
        )

        future = asyncio.run_coroutine_threadsafe(
            self._close_session_async(
                history_key=history_key,
                chat_id=chat_id,
                delay_seconds=effective_delay,
            ),
            self._loop,
        )
        try:
            return bool(future.result(timeout=10.0))
        except Exception as exc:
            log(f"[WebRouter] Error closing session tab: {exc}", "debug")
            return False

    def send_prompt(
        self,
        prompt_text,
        model=GEMINI_4_HYDROGEN,
        chat_history=None,
        print_cost=True,
        image_data=None,
        media_files=None,
        thinking_level=None,
        cancel_event: threading.Event | None = None,
        chat_id: str | None = None,
        user: int = 0,
    ):
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Prompt cancelled before dispatch.")

        if image_data or media_files:
            log(
                "[WebRouter] image_data/media_files are not yet supported in web mode; "
                "sending text prompt only.",
                "warning",
            )

        if chat_history is None:
            chat_history = []

        chat_history.append(
            types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)])
        )

        loop = self._ensure_event_loop()
        future = asyncio.run_coroutine_threadsafe(
            self._send_prompt_async(
                prompt_text=prompt_text,
                model=model,
                history_key=id(chat_history),
                thinking_level=thinking_level,
                chat_id=chat_id,
                cancel_event=cancel_event,
                user=user,
            ),
            loop,
        )

        # Poll future so cancellation interrupts promptly
        while True:
            try:
                response_text, total_tokens, captured_chat_id = future.result(timeout=0.1)
                break
            except FutureTimeoutError:
                if cancel_event and cancel_event.is_set():
                    future.cancel()
                    raise InterruptedError("Prompt cancelled.")

        cost = {
            "input_cost": 0.0,
            "output_cost": 0.0,
            "thinking_cost": 0.0,
            "total_cost": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "total_tokens": total_tokens,
            "chat_id": captured_chat_id,
        }

        if print_cost:
            log(
                f"[WebRouter] Model: {model} | Thinking: {thinking_level} | "
                f"Chat ID: {captured_chat_id} | Session tokens: {total_tokens} | Cost: $0.000000",
                "debug",
            )

        chat_history.append(
            types.Content(
                role="model",
                parts=[types.Part.from_text(text=response_text)],
            )
        )

        return response_text, chat_history, cost

    async def _shutdown_async(self) -> None:
        self._sessions_by_history_id.clear()
        self._sessions_by_chat_id.clear()

        browser = self._browser
        playwright = self._playwright
        self._browser = None
        self._context = None
        self._playwright = None

        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:
                pass

    def shutdown(self, timeout: float = 4.0) -> None:
        """Cleanly detaches Playwright/CDP and stops the background asyncio loop thread."""
        with self._loop_init_lock:
            loop = self._loop
            thread = self._loop_thread
            self._loop = None
            self._loop_thread = None

        if loop is None:
            return

        if loop.is_running():
            try:
                future = asyncio.run_coroutine_threadsafe(self._shutdown_async(), loop)
                future.result(timeout=max(0.5, timeout))
            except Exception as exc:
                log(f"[WebRouter] Shutdown cleanup warning: {exc}", "debug")
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass

        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)

        try:
            if not loop.is_running() and not loop.is_closed():
                loop.close()
        except Exception:
            pass