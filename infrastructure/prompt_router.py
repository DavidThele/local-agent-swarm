import os
import threading

from infrastructure.api_prompt_router import (  # noqa: F401 - re-exported for backward compatibility
    ApiPromptRouter,
    client,
    pricing,
)
from infrastructure.models import GEMINI_3_1_FLASH_LITE  # noqa: F401
from infrastructure.web_prompt_router import WebPromptRouter

DEFAULT_BACKEND = "api"
VALID_BACKENDS = ("api", "web")
USERS = {
    "subscribed": 0,
    "personal": 1,
}
USER = 0


class PromptRouter:
    """Routes prompts to either the Vertex AI API router or the AI Studio Web router."""

    def __init__(
        self,
        api_router: ApiPromptRouter | None = None,
        web_router: WebPromptRouter | None = None,
    ):
        self.api_router = api_router or ApiPromptRouter()
        self.web_router = web_router or WebPromptRouter()

    def send_prompt(
        self,
        prompt_text,
        model=GEMINI_3_1_FLASH_LITE,
        chat_history=None,
        print_cost=True,
        image_data=None,
        media_files=None,
        google_search=False,
        thinking_level=None,
        cancel_event: threading.Event | None = None,
        backend: str | None = None,
        chat_id: str | None = None
    ):
        resolved_backend = (
            backend
            if backend is not None
            else os.environ.get("PROMPT_ROUTER_BACKEND", DEFAULT_BACKEND)
        ).strip().lower()

        if resolved_backend == "api":
            return self.api_router.send_prompt(
                prompt_text=prompt_text,
                model=model,
                chat_history=chat_history,
                print_cost=print_cost,
                image_data=image_data,
                media_files=media_files,
                google_search=google_search,
                thinking_level=thinking_level,
                cancel_event=cancel_event,
            )
        if resolved_backend == "web":
            return self.web_router.send_prompt(
                prompt_text=prompt_text,
                model=model,
                chat_history=chat_history,
                print_cost=print_cost,
                image_data=image_data,
                media_files=media_files,
                thinking_level=thinking_level,
                cancel_event=cancel_event,
                chat_id=chat_id,
                user=USER
            )

        raise ValueError(
            f"Unknown prompt router backend {resolved_backend!r}; expected one of: {', '.join(VALID_BACKENDS)}"
        )

    def close_session(
        self,
        chat_history=None,
        chat_id: str | None = None,
        delay_seconds: float | None = None,
    ) -> bool:
        """Closes any persistent web tab associated with the given conversation."""
        return self.web_router.close_session(
            chat_history=chat_history,
            chat_id=chat_id,
            delay_seconds=delay_seconds,
        )

    def shutdown(self, timeout: float = 4.0) -> None:
        """Cleanly shuts down background router resources (e.g., WebPromptRouter event loop)."""
        self.web_router.shutdown(timeout=timeout)


_default_router = PromptRouter()


def shutdown(timeout: float = 4.0) -> None:
    _default_router.shutdown(timeout=timeout)


def close_session(
    chat_history=None,
    chat_id: str | None = None,
    delay_seconds: float | None = None,
) -> bool:
    return _default_router.close_session(
        chat_history=chat_history,
        chat_id=chat_id,
        delay_seconds=delay_seconds,
    )


def send_prompt(
    prompt_text,
    model=GEMINI_3_1_FLASH_LITE,
    chat_history=None,
    print_cost=True,
    image_data=None,
    media_files=None,
    google_search=False,
    thinking_level=None,
    cancel_event: threading.Event | None = None,
    backend: str | None = None,
    chat_id: str | None = None,
):
    return _default_router.send_prompt(
        prompt_text=prompt_text,
        model=model,
        chat_history=chat_history,
        print_cost=print_cost,
        image_data=image_data,
        media_files=media_files,
        google_search=google_search,
        thinking_level=thinking_level,
        cancel_event=cancel_event,
        backend=backend,
        chat_id=chat_id,
    )
