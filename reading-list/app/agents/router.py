# ABOUTME: AgentRouter coordinates multiple specialized agents using message passing.
# ABOUTME: Implements the "prompt object" paradigm where agents communicate semantically.

"""
AgentRouter - Multi-Agent Message Passing Coordinator

This module implements the message-passing paradigm from Smalltalk/OOP applied to AI agents.
Each agent is a "prompt object" that:
1. Has its own personality (skill file)
2. Has its own capabilities (tools)
3. Communicates with other agents via semantic messages

The router:
- Manages agent lifecycle (creation, connection, cleanup)
- Routes messages between agents
- Tracks conversation history for debugging/evals
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import json
import asyncio


@dataclass
class AgentMessage:
    """A message passed between agents."""
    timestamp: str
    from_agent: str
    to_agent: str
    message: str
    response: str | None = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "from": self.from_agent,
            "to": self.to_agent,
            "message": self.message,
            "response": self.response
        }


@dataclass
class MessageLog:
    """Log of all inter-agent messages for debugging and evals."""
    messages: list[AgentMessage] = field(default_factory=list)

    def add(self, msg: AgentMessage):
        self.messages.append(msg)

    def clear(self):
        self.messages.clear()

    def to_json(self) -> str:
        return json.dumps([m.to_dict() for m in self.messages], indent=2)

    def get_messages_from(self, agent: str) -> list[AgentMessage]:
        return [m for m in self.messages if m.from_agent == agent]

    def get_messages_to(self, agent: str) -> list[AgentMessage]:
        return [m for m in self.messages if m.to_agent == agent]


class AgentRouter:
    """
    Coordinates multiple specialized agents using message passing.

    Agents:
    - ui: Handles user interaction and HTML generation
    - recommender: Specializes in book recommendations
    - insights: Analyzes reading patterns and behavior

    Message passing works by:
    1. An agent calls the message_agent tool with (target_agent, message)
    2. Router routes the message to the target agent
    3. Target agent processes and returns response
    4. Response is returned to the calling agent
    """

    def __init__(self):
        self.message_log = MessageLog()
        self._agents: dict[str, Any] = {}
        self._initialized = False

    async def initialize(self):
        """Initialize all agents."""
        if self._initialized:
            return

        # Import here to avoid circular imports
        from .ui_agent import UIAgent
        from .recommender_agent import RecommenderAgent
        from .insights_agent import InsightsAgent

        # Create agents with reference to router for inter-agent messaging
        self._agents = {
            "ui": UIAgent(self),
            "recommender": RecommenderAgent(self),
            "insights": InsightsAgent(self),
        }

        self._initialized = True

    async def close(self):
        """Clean up all agents."""
        for agent in self._agents.values():
            if hasattr(agent, 'close'):
                await agent.close()
        self._agents.clear()
        self._initialized = False

    async def reset(self):
        """Reset all agents and message log."""
        self.message_log.clear()
        for agent in self._agents.values():
            if hasattr(agent, 'reset'):
                await agent.reset()

    def get_agent_names(self) -> list[str]:
        """Get list of available agent names."""
        return list(self._agents.keys())

    def get_agent_descriptions(self) -> dict[str, str]:
        """Get descriptions of all agents for inter-agent awareness."""
        return {
            "ui": "Handles user interaction, generates HTML UI, coordinates with other agents",
            "recommender": "Specializes in book recommendations based on reading history and preferences",
            "insights": "Analyzes reading patterns, identifies trends, provides behavioral insights",
        }

    async def process_user_message(self, message: str) -> str:
        """
        Process a message from the user.
        Always routes to UI agent first, which may delegate to specialists.
        """
        await self.initialize()

        # Log user message
        msg = AgentMessage(
            timestamp=datetime.now().isoformat(),
            from_agent="user",
            to_agent="ui",
            message=message,
        )

        try:
            response = await self._agents["ui"].process(message)
            # Truncate response for logging (HTML can be large)
            msg.response = response[:500] + "..." if len(response) > 500 else response
        except Exception as e:
            msg.response = f"Error: {str(e)}"
            self.message_log.add(msg)
            raise

        self.message_log.add(msg)
        return response

    async def route_agent_message(self, from_agent: str, to_agent: str, message: str) -> str:
        """
        Route a message from one agent to another.

        This is the core of the message-passing paradigm.
        Agents don't call each other's methods - they send messages.
        """
        await self.initialize()

        if to_agent not in self._agents:
            return f"Error: Unknown agent '{to_agent}'. Available agents: {', '.join(self._agents.keys())}"

        if from_agent == to_agent:
            return "Error: Agent cannot message itself"

        # Log the message
        msg = AgentMessage(
            timestamp=datetime.now().isoformat(),
            from_agent=from_agent,
            to_agent=to_agent,
            message=message,
        )

        # Route to target agent
        try:
            response = await self._agents[to_agent].process(message)
            msg.response = response
        except Exception as e:
            msg.response = f"Error: {str(e)}"
            response = msg.response

        self.message_log.add(msg)
        return response

    def get_message_log(self) -> MessageLog:
        """Get the message log for debugging/evals."""
        return self.message_log
