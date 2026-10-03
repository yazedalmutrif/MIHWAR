"""Agent registry: the orchestrator (#0) plus 8 specialist agents."""
from .compliance import ComplianceAgent
from .documents import DocumentsAgent
from .intake import IntakeAgent
from .planner import PlannerAgent
from .proposal import ProposalAgent
from .reporting import ReportingAgent
from .security import SecurityAgent
from .team import TeamAgent

SPECIALISTS = (IntakeAgent, ProposalAgent, PlannerAgent, TeamAgent, DocumentsAgent, ComplianceAgent, SecurityAgent, ReportingAgent)

__all__ = ["SPECIALISTS", "IntakeAgent", "ProposalAgent", "PlannerAgent", "TeamAgent", "DocumentsAgent",
           "ComplianceAgent", "SecurityAgent", "ReportingAgent"]
