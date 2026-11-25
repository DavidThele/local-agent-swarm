from enum import Enum
import os

from infrastructure.models import GEMINI_4_HYDROGEN


class AgentType(str, Enum):
    MAIN_ORCHESTRATOR = "main_orchestrator"
    SUB_ORCHESTRATOR = "sub_orchestrator"
    WORKER = "worker"

    @classmethod
    def parse(cls, value: "AgentType | str") -> "AgentType":
        if isinstance(value, cls):
            return value

        normalized = value.strip().lower().replace("-", "_")
        try:
            return cls(normalized)
        except ValueError as exc:
            valid_types = ", ".join(agent_type.value for agent_type in cls)
            raise ValueError(
                f"Unknown agent type {value!r}; expected one of: {valid_types}"
            ) from exc

    @property
    def prompt_filename(self) -> str:
        return f"{self.name.lower()}.md"

    @property
    def id_prefix(self) -> str:
        return self.value

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @property
    def commands(self) -> tuple[str, ...]:
        return {
            AgentType.MAIN_ORCHESTRATOR: (
                "chat_title",
                "search_db",
                "spawn_agent",
                "wait_for_agents",
                "question",
                "mark_done",
                "chrome",
                "wait_for_user",
                "read_file",
                "list_directory",
                "zsh",
            ),
            AgentType.SUB_ORCHESTRATOR: (
                "spawn_agent",
                "wait_for_agents",
                "mark_done",
                "read_file",
                "list_directory",
                "zsh",
            ),
            AgentType.WORKER: (
                "zsh",
                "write_file",
                "read_file",
                "list_directory",
                "mark_done",
                "chrome",
                "wait_for_user",
            ),
        }[self]

    @property
    def model(self) -> str:
        env_key = f"AGENT_MODEL_{self.name}"
        return os.environ.get(env_key) or AGENT_MODEL_DEFAULTS[self]

    @property
    def thinking_level(self) -> str:
        env_key = f"AGENT_THINKING_{self.name}"
        return os.environ.get(env_key) or AGENT_THINKING_LEVEL_DEFAULTS[self]


# Customizable default models and thinking levels per agent role.
# Override either here or via env vars:
#   AGENT_MODEL_MAIN_ORCHESTRATOR / AGENT_THINKING_MAIN_ORCHESTRATOR
#   AGENT_MODEL_SUB_ORCHESTRATOR  / AGENT_THINKING_SUB_ORCHESTRATOR
#   AGENT_MODEL_WORKER            / AGENT_THINKING_WORKER
AGENT_MODEL_DEFAULTS: dict[AgentType, str] = {
    AgentType.MAIN_ORCHESTRATOR: GEMINI_4_HYDROGEN,
    AgentType.SUB_ORCHESTRATOR: GEMINI_4_HYDROGEN,
    AgentType.WORKER: GEMINI_4_HYDROGEN,
}

AGENT_THINKING_LEVEL_DEFAULTS: dict[AgentType, str] = {
    AgentType.MAIN_ORCHESTRATOR: "High",
    AgentType.SUB_ORCHESTRATOR: "High",
    AgentType.WORKER: "Medium",
}
