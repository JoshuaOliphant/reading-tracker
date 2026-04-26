# ABOUTME: Recommender Agent specializes in book recommendations.
# ABOUTME: Analyzes reading history and preferences to suggest next reads.

"""
Recommender Agent - Book Recommendation Specialist

Responsibilities:
1. Analyze user's reading history (finished books, ratings)
2. Identify preferences and patterns
3. Generate personalized book recommendations
4. Explain reasoning behind recommendations

This agent returns TEXT responses (not HTML) because it's typically
called by the UI agent, which handles HTML generation.
"""

from pathlib import Path
from typing import TYPE_CHECKING
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
)
from .base_agent import BaseAgent
from ..tools import list_books, get_stats, get_recent_activity

if TYPE_CHECKING:
    from .router import AgentRouter

SKILL_PATH = Path(__file__).parent.parent / "skills" / "recommender.md"


class RecommenderAgent(BaseAgent):
    """Agent specialized in book recommendations."""

    def __init__(self, router: "AgentRouter"):
        super().__init__(router, "recommender")
        self.client: ClaudeSDKClient | None = None
        self._connected = False

    def _load_skill_file(self) -> str:
        """Load the recommender skill file."""
        if SKILL_PATH.exists():
            return SKILL_PATH.read_text()
        return self._default_skill()

    def _default_skill(self) -> str:
        """Default skill if file doesn't exist."""
        return """# Book Recommender Agent

You are a book recommendation specialist. Your job is to analyze reading history
and provide personalized book recommendations.

## Your Personality
- Enthusiastic about books and reading
- Knowledgeable about many genres
- Thoughtful about matching books to readers
- Clear about your reasoning

## How You Work
1. First, use list_books to see what the user has read
2. Use get_stats to understand their reading patterns
3. Analyze their preferences (genres, authors, ratings)
4. Generate recommendations with explanations

## Response Format
Return a structured TEXT response (not HTML) with:
- 2-3 book recommendations
- Brief explanation for each recommendation
- How it relates to their reading history

Example response:
"Based on your reading history, I recommend:

1. **The Name of the Wind** by Patrick Rothfuss
   You rated fantasy books highly (avg 4.5 stars) and enjoyed intricate magic systems.

2. **Project Hail Mary** by Andy Weir
   Your 5-star rating of sci-fi suggests you'd enjoy this page-turner.

3. **Piranesi** by Susanna Clarke
   A unique blend of fantasy and mystery that matches your diverse tastes."
"""

    def _build_system_prompt(self) -> str:
        """Build complete system prompt."""
        skill_content = self._load_skill_file()
        agent_awareness = self._get_agent_awareness_prompt()

        return f"""{skill_content}

{agent_awareness}

## Important Notes
- You return TEXT responses, not HTML
- You are typically called by the UI agent
- You can message the insights agent for deeper pattern analysis
- Always use list_books and get_stats to understand the user's reading history
"""

    def _create_mcp_server(self):
        """Create MCP server with tools needed for recommendations."""
        from claude_agent_sdk import create_sdk_mcp_server

        message_tool = self._create_message_agent_tool()

        return create_sdk_mcp_server(
            name="recommender_tools",
            version="1.0.0",
            tools=[
                list_books,
                get_stats,
                get_recent_activity,
                message_tool,
            ]
        )

    async def _ensure_connected(self) -> None:
        """Initialize and connect if not already connected."""
        if self._connected and self.client:
            return

        tools_server = self._create_mcp_server()

        options = ClaudeAgentOptions(
            system_prompt=self._build_system_prompt(),
            mcp_servers={"recommender_tools": tools_server},
            allowed_tools=[
                "mcp__recommender_tools__list_books",
                "mcp__recommender_tools__get_stats",
                "mcp__recommender_tools__get_recent_activity",
                "mcp__recommender_tools__message_agent",
            ],
            permission_mode="acceptEdits",
        )

        self.client = ClaudeSDKClient(options=options)
        await self.client.connect()
        self._connected = True

    async def process(self, message: str) -> str:
        """Process message and return text recommendations."""
        await self._ensure_connected()
        await self.client.query(message)
        return (await self._collect_response(self.client)).strip()

    async def reset(self):
        """Reset conversation state."""
        if self.client:
            await self.client.disconnect()
            self.client = None
            self._connected = False

    async def close(self):
        """Clean up resources."""
        await self.reset()
