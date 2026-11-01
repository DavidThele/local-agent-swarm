from enum import Enum

from infrastructure.prompt_router import GEMINI_3_1_FLASH_LITE, GEMINI_3_8_FLASH


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
                "search_db",
                "spawn_agent",
                "wait_for_agents",
                "question",
                "mark_done",
            ),
            AgentType.SUB_ORCHESTRATOR: (
                "spawn_agent",
                "wait_for_agents",
                "mark_done",
            ),
            AgentType.WORKER: (
                "zsh",
                "write_file",
                "read_file",
                "list_directory",
                "mark_done",
            ),
        }[self]

    @property
    def model(self):
        return (
            GEMINI_3_8_FLASH
            if self is AgentType.MAIN_ORCHESTRATOR
            else GEMINI_3_1_FLASH_LITE
        )