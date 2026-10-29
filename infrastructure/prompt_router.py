import sys
import time
from google import genai
from google.genai.errors import APIError
from google.genai.types import HttpOptions
from google.genai import types
from infrastructure.debug_colors import debug_print

# Cleaned up model strings (stripped accidental leading spaces)
GEMINI_4_ARGON = "gemini-4-argon"
GEMINI_3_1_PRO = "gemini-3.1-pro-preview"
GEMINI_3_8_FLASH = "gemini-3.8-flash"
GEMINI_3_5_FLASH_LITE = "gemini-3.5-flash-lite"
GEMINI_3_1_FLASH_LITE = "gemini-3.1-flash-lite"
GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"

discount = 0.5
discounted_models = [GEMINI_3_8_FLASH, GEMINI_4_ARGON]

pricing = {
    GEMINI_4_ARGON: {
        "input": 4,
        "output": 20,
        "thinking": 20,
    },
    GEMINI_3_1_PRO: {
        "input": 2.00,
        "output": 4.00,
        "thinking": 4.00,
    },
    GEMINI_3_8_FLASH: {
        "input": 1.50,
        "output": 7.50,
        "thinking": 7.50,
    },
    GEMINI_3_5_FLASH_LITE: {
        "input": 0.30,
        "output": 2.50,
        "thinking": 2.50,
    },
    GEMINI_3_1_FLASH_LITE: {
        "input": 0.25,
        "output": 1.50,
        "thinking": 1.50,
    },
    GEMINI_2_5_FLASH_LITE: {
        "input": 0.10,
        "output": 0.40,
        "thinking": 0.40,
    },
}


def send_prompt(prompt_text, model=GEMINI_2_5_FLASH_LITE, chat_history=None, print_cost=True):
    if chat_history is None:
        chat_history = []

    client = genai.Client(http_options=HttpOptions(api_version="v1"))
    chat_history.append(
        types.Content(
            role="user",
            parts=[types.Part(text=prompt_text)],
        )
    )

    delays = [10, 20, 30]
    response = None

    for attempt, delay in enumerate(delays, start=1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=chat_history,
            )
            break
        except APIError as e:
            if getattr(e, "code", None) == 429 or "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                debug_print(f"[Router] 429 RESOURCE_EXHAUSTED encountered on attempt {attempt}/3. Sleeping for {delay}s...", "warning")
                time.sleep(delay)
            else:
                raise e
    else:
        # Final attempt after the 30s sleep
        try:
            response = client.models.generate_content(
                model=model,
                contents=chat_history,
            )
        except APIError as e:
            if getattr(e, "code", None) == 429 or "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                debug_print("[Router] Exceeded retry attempts (10s, 20s, 30s). Quitting execution.", "error")
                sys.exit(1)
            raise e

    usage = response.usage_metadata

    input_tokens = usage.prompt_token_count or 0
    output_tokens = usage.candidates_token_count or 0
    thinking_tokens = getattr(usage, "thoughts_token_count", 0) or 0

    input_cost = input_tokens / 1e6 * pricing[model]['input']
    output_cost = output_tokens / 1e6 * pricing[model]['output']
    thinking_cost = thinking_tokens / 1e6 * pricing[model]['thinking']
    total_cost = input_cost + output_cost + thinking_cost

    if model in discounted_models:
        input_cost *= discount
        output_cost *= discount
        thinking_cost *= discount
        total_cost *= discount

    cost = {
        "input_cost": input_cost,
        "output_cost": output_cost,
        "thinking_cost": thinking_cost,
        "total_cost": total_cost,
    }

    if print_cost:
        debug_print(f"[Router] Model: {model}", "debug")
        debug_print(f"[Router] Input tokens: {input_tokens}", "debug")
        debug_print(f"[Router] Output tokens: {output_tokens}", "debug")
        debug_print(f"[Router] Thinking tokens: {thinking_tokens}", "debug")
        debug_print(f"[Router] Total tokens: {input_tokens + output_tokens + thinking_tokens}", "debug")
        debug_print(f"[Router] Input cost: ${input_cost:.6f}", "debug")
        debug_print(f"[Router] Output cost: ${output_cost:.6f}", "debug")
        debug_print(f"[Router] Thinking cost: ${thinking_cost:.6f}", "debug")
        debug_print(f"[Router] Total cost: ${total_cost:.6f}", "debug")
        if total_cost > 0.05:
            debug_print(f"[Router] Cost warning: ${total_cost:.6f} exceeds $0.05 threshold.", "error")
        elif total_cost > 0.01:
            debug_print(f"[Router] Cost notice: ${total_cost:.6f} exceeds $0.01 threshold.", "warning")

    chat_history.append(
        types.Content(
            role="model",
            parts=[types.Part.from_text(text=response.text)],
        )
    )
    return response.text, chat_history, cost