# === File: command_executors/chrome_exec.py ===
import os
import time
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from infrastructure.debugging import debug_print

# Global state to persist the browser connection across agent turns
_PLAYWRIGHT = None
_BROWSER = None
_CONTEXT = None
_PAGE = None

# Injected JS to clear old markers, find interactive elements, tag them with IDs, and draw overlays
DOM_SCRIPT = """
() => {
    document.querySelectorAll('.agent-overlay-label').forEach(e => e.remove());
    document.querySelectorAll('[data-agent-id]').forEach(e => {
        e.style.outline = '';
        e.removeAttribute('data-agent-id');
    });

    let idCounter = 1;
    const elements = [];
    const interactives = document.querySelectorAll('a, button, input, textarea, select, [role="button"], [role="link"], [tabindex]:not([tabindex="-1"])');
    
    interactives.forEach(el => {
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden') {
            const myId = idCounter++;
            el.setAttribute('data-agent-id', myId);
            el.style.outline = '2px solid rgba(255, 0, 0, 0.6)';
            
            const label = document.createElement('div');
            label.className = 'agent-overlay-label';
            label.innerText = myId;
            label.style.position = 'absolute';
            label.style.background = 'red';
            label.style.color = 'white';
            label.style.fontSize = '12px';
            label.style.fontWeight = 'bold';
            label.style.padding = '1px 3px';
            label.style.zIndex = '999999';
            label.style.top = (rect.top + window.scrollY) + 'px';
            label.style.left = (rect.left + window.scrollX) + 'px';
            document.body.appendChild(label);

            let text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').substring(0, 60).replace(/\\n/g, ' ');
            elements.push(`[${myId}] <${el.tagName.toLowerCase()}> "${text.trim()}"`);
        }
    });
    return elements.join('\\n');
}
"""

def launch_chrome_if_needed():
    """Checks if the debug port is open. If not, spawns Chrome and waits for it to load."""
    port = 9222
    url = f"http://localhost:{port}/json/version"
    
    # Check if Chrome is already listening
    try:
        urllib.request.urlopen(url, timeout=1)
        return  # Already running
    except urllib.error.URLError:
        pass
        
    debug_print("[Chrome] Starting new Chrome instance with agent profile...", "info")
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    profile_dir = os.path.expanduser("~/.agents/chrome_profile")
    os.makedirs(profile_dir, exist_ok=True)
    
    cmd = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check"
    ]
    
    # Launch in the background
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    
    # Poll until the debugger endpoint is responsive
    max_attempts = 20
    for _ in range(max_attempts):
        try:
            urllib.request.urlopen(url, timeout=1)
            time.sleep(0.5)  # Give Playwright a moment to sync with the new process
            debug_print("[Chrome] Browser loaded and ready.", "success")
            return
        except urllib.error.URLError:
            time.sleep(0.5)
            
    raise RuntimeError("Timed out waiting for Chrome to open debugging port 9222.")

def init_browser():
    global _PLAYWRIGHT, _BROWSER, _CONTEXT, _PAGE
    if _PAGE is not None:
        return

    launch_chrome_if_needed()

    debug_print("[Chrome] Connecting to Chrome via CDP...", "info")
    try:
        _PLAYWRIGHT = sync_playwright().start()
        _BROWSER = _PLAYWRIGHT.chromium.connect_over_cdp("http://localhost:9222")
        _CONTEXT = _BROWSER.contexts[0] if _BROWSER.contexts else _BROWSER.new_context()
        _PAGE = _CONTEXT.pages[0] if _CONTEXT.pages else _CONTEXT.new_page()
    except Exception as e:
        raise RuntimeError(f"Failed to connect to Chrome via Playwright: {e}")

def execute(attributes: dict, content: dict | str, context_state: dict) -> str:
    global _PAGE, _BROWSER, _PLAYWRIGHT, _CONTEXT
    
    action = attributes.get("action", "").lower()
    if not action:
        return "[Error] Chrome command requires an 'action' attribute (navigate, click, type, scroll, close)."
        
    try:
        if action != "close":
            init_browser()
    except RuntimeError as e:
        return f"[Error] {e}"

    result_msg = ""
    
    try:
        if action == "navigate":
            url = attributes.get("url")
            if not url: return "[Error] Navigate requires a 'url' attribute."
            if not url.startswith("http"): url = "https://" + url
            _PAGE.goto(url, wait_until="domcontentloaded")
            try: _PAGE.wait_for_load_state("networkidle", timeout=4000)
            except PlaywrightTimeoutError: pass
            result_msg = f"Navigated to {url}"
            
        elif action == "click":
            target_id = attributes.get("target_id")
            if not target_id: return "[Error] Click requires a 'target_id'."
            locator = _PAGE.locator(f"[data-agent-id='{target_id}']")
            if locator.count() == 0: return f"[Error] Element ID {target_id} not found."
            locator.first.click()
            try: _PAGE.wait_for_load_state("networkidle", timeout=3000)
            except PlaywrightTimeoutError: pass
            result_msg = f"Clicked element [{target_id}]"

        elif action == "type":
            target_id = attributes.get("target_id")
            if isinstance(content, dict):
                text = content.get("Text", "")
                if isinstance(text, list): text = text[0]
            else:
                text = str(content)
                
            if not target_id: return "[Error] Type requires a 'target_id'."
            locator = _PAGE.locator(f"[data-agent-id='{target_id}']")
            if locator.count() == 0: return f"[Error] Element ID {target_id} not found."
            locator.first.fill(text)
            result_msg = f"Typed text into element [{target_id}]"
            
        elif action == "scroll":
            direction = attributes.get("direction", "down")
            if direction == "down": _PAGE.mouse.wheel(0, 800)
            else: _PAGE.mouse.wheel(0, -800)
            time.sleep(0.5)
            result_msg = f"Scrolled {direction}"

        elif action == "close":
            if _BROWSER:
                _BROWSER.close()
                _PLAYWRIGHT.stop()
                _BROWSER, _CONTEXT, _PAGE = None, None, None
            return "[Success] Chrome session detached."
            
        else:
            return f"[Error] Unknown action '{action}'"

        # Extract ID-based DOM
        dom_string = _PAGE.evaluate(DOM_SCRIPT)
        
        # Save screenshot
        chat_dir = Path(context_state.get("local_chat_dir", ".agents/chats/default"))
        screenshot_path = chat_dir / f"chrome_{int(time.time())}.png"
        _PAGE.screenshot(path=str(screenshot_path))
        
        return f"[Success] {result_msg}\n\n=== INTERACTIVE DOM ELEMENTS ===\n{dom_string}\n"

    except Exception as e:
        return f"[Error] Chrome action '{action}' failed: {str(e)}"