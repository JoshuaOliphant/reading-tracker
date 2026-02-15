# ABOUTME: Base agent class providing common functionality for all specialized agents.
# ABOUTME: Includes inter-agent messaging tool and common setup patterns.

"""
BaseAgent - Foundation for specialized agents in the message-passing system.

Each agent:
1. Has its own skill file (personality/instructions)
2. Has access to shared data tools (book CRUD)
3. Has a message_agent tool to communicate with other agents
4. Can be messaged by other agents
"""

from abc import ABC, abstractmethod
from claude_agent_sdk import tool, create_sdk_mcp_server
from typing import Any, TYPE_CHECKING
import json

if TYPE_CHECKING:
    from .router import AgentRouter


class BaseAgent(ABC):
    """Base class for all agents in the multi-agent system."""

    def __init__(self, router: "AgentRouter", agent_name: str):
        self.router = router
        self.agent_name = agent_name
        self._tools_server = None

    @abstractmethod
    async def process(self, message: str) -> str:
        """Process a message and return a response."""
        pass

    @abstractmethod
    async def reset(self):
        """Reset agent state."""
        pass

    @abstractmethod
    async def close(self):
        """Clean up resources."""
        pass

    def _create_message_agent_tool(self):
        """
        Create the inter-agent messaging tool.

        This is the key to the message-passing paradigm:
        agents communicate by sending semantic messages, not by
        calling each other's internal methods.
        """
        router = self.router
        agent_name = self.agent_name

        @tool(
            "message_agent",
            f"""Send a message to another agent and get their response.

Available agents:
- recommender: Specializes in book recommendations. Ask when user wants suggestions for what to read next.
- insights: Analyzes reading patterns. Ask when you need to understand reading behavior or patterns.

Use this tool when:
- The user's request requires specialized knowledge you don't have
- You need analysis or recommendations from a specialist
- You want to delegate part of a task to a more appropriate agent

Do NOT message yourself ({agent_name}).
""",
            {"target_agent": str, "message": str}
        )
        async def message_agent(args: dict[str, Any]) -> dict[str, Any]:
            """Send a message to another agent."""
            target = args.get("target_agent", "")
            msg = args.get("message", "")

            if not target or not msg:
                return {
                    "content": [{"type": "text", "text": json.dumps({"error": "Both target_agent and message are required"})}],
                    "is_error": True
                }

            # Route through the router
            response = await router.route_agent_message(agent_name, target, msg)

            return {
                "content": [{"type": "text", "text": json.dumps({"agent": target, "response": response})}]
            }

        return message_agent

    def _get_agent_awareness_prompt(self) -> str:
        """
        Generate prompt section that makes this agent aware of other agents.
        """
        descriptions = self.router.get_agent_descriptions()
        other_agents = {k: v for k, v in descriptions.items() if k != self.agent_name}

        lines = [
            "## Other Agents You Can Message",
            "",
            "You are part of a multi-agent system. Use the message_agent tool to communicate with:",
            ""
        ]

        for name, desc in other_agents.items():
            lines.append(f"- **{name}**: {desc}")

        lines.extend([
            "",
            "When to message other agents:",
            "- Message 'recommender' when user asks for book suggestions or 'what to read next'",
            "- Message 'insights' when you need analysis of reading patterns or behavior",
            "",
            "Always include relevant context in your message to the other agent.",
        ])

        return "\n".join(lines)
