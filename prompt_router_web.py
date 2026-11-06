import re
import time
from typing import Optional, Tuple
from playwright.sync_api import sync_playwright

ARGON = "Gemini 4 Argon"
FLASH_3_8 = "Gemini 3.8 Flash"
FLASH_LITE_3_8 = "Gemini 3.5 Flash Lite"
FLASH_3_6 = "Gemini 3.6 Flash"
FLASH_LITE_3_1 = "Gemini 3.1 Flash Lite"
PRO = "Gemini 3.1 Pro Preview"
GEMMA_26 = "Gemma 4 26B A4B IT"
GEMMA_31 = "Gemma 4 31B IT"



def send_prompt(
    prompt_text: str,
    conversation_id: Optional[str] = None,
    model_name: str = FLASH_LITE_3_8,
    cdp_url: str = "http://localhost:9222",
    timeout: int = 60000,
) -> Tuple[str, Optional[str]]:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()

        # 1. Navigation
        if conversation_id:
            print(f"Navigating to conversation ID: {conversation_id}")
            target_url = f"https://aistudio.google.com/prompts/{conversation_id}"
            if not page.url.startswith(target_url):
                page.goto(target_url, wait_until="domcontentloaded")
        else:
            print("Navigating to new chat")
            page.goto("https://aistudio.google.com/prompts/new_chat", wait_until="domcontentloaded")

        # Open model panel if not already open
        if not page.locator("text='Model selection'").is_visible():
            print("Opening model selection panel")
            page.getByRole('button', name='Gemini 3.8 Flash').click()
            page.wait_for_selector("mat-dialog-container")

        # Switch to 'All' category tab
        print("Switching to 'All' category tab")
        page.locator("button, div[role='tab']").filter(has_text=re.compile(r"^All$")).first.click()

        # Search to isolate the card
        print(f"Searching for model: {model_name}")
        search_input = page.locator("input[placeholder*='Search for a model']").first
        if search_input.is_visible():
            search_input.fill(model_name)
            page.wait_for_timeout(350)

        # Click the matching model card
        print(f"Clicking model card for: {model_name}")
        model_card = page.locator(f"text='{model_name}'").first
        model_card.scroll_into_view_if_needed()
        model_card.click()
        page.wait_for_timeout(500)

        # 3. Enter Prompt
        print("Entering prompt text")
        textarea = page.locator('div[contenteditable="true"]').first or page.get_by_placeholder("Type something")
        textarea.wait_for(state="visible", timeout=15000)
        textarea.fill(prompt_text)

        # 4. Submit with Cmd+Enter
        print("Submitting prompt with Cmd+Enter")
        textarea.press("Meta+Enter")

        # 5. Wait for Generation to Complete
        print("Waiting for generation to complete")
        # The primary run button is disabled or toggled into a stop/spinner state during generation
        run_button = page.get_by_role("button", name="Run", exact=True)
        run_button.wait_for(state="attached", timeout=timeout)

        # Brief pause to ensure generation state registers
        page.wait_for_timeout(100)

        # Wait until Run button is active again (not aria-disabled and not disabled)
        page.wait_for_function(
            """(btn) => !btn.disabled && btn.getAttribute('aria-disabled') !== 'true'""",
            arg=run_button.element_handle(),
            timeout=timeout,
        )

        # 6. Read Latest Response
        print("Reading latest response")
        model_turn = page.locator(".chat-turn-container.model").last
        model_turn.wait_for(state="visible", timeout=timeout)

        chunk = model_turn.locator("ms-text-chunk").first
        chunk.wait_for(state="visible", timeout=timeout)
        response_text = chunk.inner_text().strip()

        # 7. Extract the Current / Resulting Conversation ID
        print("Extracting conversation ID from URL")
        # AI Studio updates the URL via client-side routing from /new_chat to /prompts/<id>
        url_match = re.search(r"/prompts/([a-zA-Z0-9_\-]+)", page.url)
        extracted_id = conversation_id
        if url_match and url_match.group(1) != "new_chat":
            extracted_id = url_match.group(1)

        return response_text, extracted_id