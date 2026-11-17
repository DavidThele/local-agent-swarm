import os
import sys
import time

from google import genai
from google.genai import types
from google.genai.errors import APIError
from infrastructure.debugging import debug_print
from infrastructure.models import (  # noqa: F401 - re-exported for callers importing constants from here
    GEMINI_3_1_FLASH_LITE,
    get_resolved_pricing,
)

# Resolve active pricing table at import time
pricing = get_resolved_pricing()

project = os.environ.get("GOOGLE_CLOUD_PROJECT")

client = genai.Client(vertexai=True, project=project, location="global")


def send_prompt(
    prompt_text,
    model=GEMINI_3_1_FLASH_LITE,
    chat_history=None,
    print_cost=True,
    image_data=None,
    media_files=None,
    google_search=False,
):
    if chat_history is None:
        chat_history = []

    prompt_parts = []

    # Allow passing pre-uploaded files (like screen recording videos)
    if media_files:
        prompt_parts.extend(media_files)

    prompt_parts.append(types.Part.from_text(text=prompt_text))

    if isinstance(image_data, list):
        for label, image_bytes in image_data:
            prompt_parts.append(types.Part.from_text(text=f"Screenshot of {label}:"))
            prompt_parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
    elif image_data:
        prompt_parts.append(types.Part.from_bytes(data=image_data, mime_type="image/png"))

    chat_history.append(types.Content(role="user", parts=prompt_parts))

    delays = [10, 20, 30]
    response = None

    config: types.GenerateContentConfig | None = None
    if google_search:
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )

    for attempt, delay in enumerate(delays, start=1):
        try:
            debug_print(f"Calling generate_content with model = {repr(model)}", "debug")
            response = client.models.generate_content(
                model=model,
                contents=chat_history,
                config=config,
            )
            break
        except APIError as e:
            if getattr(e, "code", None) == 429 or "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                debug_print(
                    f"[Router] 429 RESOURCE_EXHAUSTED encountered on attempt {attempt}/3. Sleeping for {delay}s...",
                    "warning",
                )
                time.sleep(delay)
            else:
                raise
    else:
        try:
            debug_print(f"Final retry calling generate_content with model = {repr(model)}", "debug")
            response = client.models.generate_content(
                model=model,
                contents=chat_history,
                config=config,
            )
        except APIError as e:
            if getattr(e, "code", None) == 429 or "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                debug_print("[Router] Exceeded retry attempts (10s, 20s, 30s). Quitting execution.", "error")
                sys.exit(1)
            raise

    usage = response.usage_metadata
    input_tokens = (usage.prompt_token_count or 0) if usage else 0
    output_tokens = (usage.candidates_token_count or 0) if usage else 0
    thinking_tokens = (getattr(usage, "thoughts_token_count", 0) or 0) if usage else 0

    model_rates = pricing.get(model, {"input": 0.0, "output": 0.0, "thinking": 0.0})
    input_cost = (input_tokens / 1e6) * model_rates["input"]
    output_cost = (output_tokens / 1e6) * model_rates["output"]
    thinking_cost = (thinking_tokens / 1e6) * model_rates["thinking"]
    total_cost = input_cost + output_cost + thinking_cost

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

    if response.text is None:
        debug_print("[Router] Warning: Received empty response from model.", "warning")
        response_text = ""
    else:
        response_text = response.text

    chat_history.append(
        types.Content(
            role="model",
            parts=[types.Part.from_text(text=response_text)],
        )
    )

    return response_text, chat_history, cost