"""Application context: settings, database, LLM client, agents, orchestrator, scenario runner."""
from __future__ import annotations

from .agents import SPECIALISTS
from .config import Settings, load_settings
from .db import Database
from .llm import LLM


class Context:
    def __init__(self, settings: Settings | None = None, db: Database | None = None):
        from .orchestrator import Orchestrator, OrchestratorAgent
        from .scenario import ScenarioRunner

        self.settings = settings or load_settings()
        self.db = db or Database(self.settings.db_path)
        self.llm = LLM(self.settings)
        self.agents = {"orchestrator": OrchestratorAgent(self)}
        for cls in SPECIALISTS:
            self.agents[cls.key] = cls(self)
        self.orchestrator = Orchestrator(self)
        self.scenarios = ScenarioRunner(self)

    def ordered_agents(self):
        return sorted(self.agents.values(), key=lambda a: a.order)
