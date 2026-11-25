from enum import Enum
import os

from runtime import (
    AGENT_COMMANDS,
    AGENT_MODEL_DEFAULTS as _RUNTIME_AGENT_MODEL_DEFAULTS,
    AGENT_THINKING_LEVEL_DEFAULTS as _RUNTIME_AGENT_THINKING_LEVEL_DEFAULTS,
)


class AgentType(str, Enum):
    MAIN_ORCHESTRATOR = "main_orchestrator"
    SUB_ORCHESTRATOR = "sub_orchestrator"
    WORKER = "worker"
    WEB_MCP = "web_mcp"

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
        return AGENT_COMMANDS[self.value]

    @property
    def model(self) -> str:
        env_key = f"AGENT_MODEL_{self.name}"
        return os.environ.get(env_key) or AGENT_MODEL_DEFAULTS[self]

    @property
    def thinking_level(self) -> str:
        env_key = f"AGENT_THINKING_{self.name}"
        return os.environ.get(env_key) or AGENT_THINKING_LEVEL_DEFAULTS[self]


# Default models and thinking levels per agent role, sourced from root runtime.py.
AGENT_MODEL_DEFAULTS: dict[AgentType, str] = {
    role: _RUNTIME_AGENT_MODEL_DEFAULTS[role.value] for role in AgentType
}

AGENT_THINKING_LEVEL_DEFAULTS: dict[AgentType, str] = {
    role: _RUNTIME_AGENT_THINKING_LEVEL_DEFAULTS[role.value] for role in AgentType
}
