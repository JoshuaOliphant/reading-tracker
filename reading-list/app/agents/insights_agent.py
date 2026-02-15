# ABOUTME: Insights Agent analyzes reading patterns and behavior.
# ABOUTME: Identifies trends, preferences, and provides behavioral analysis.

"""
Insights Agent - Reading Pattern Analyst

Responsibilities:
1. Analyze reading history for patterns
2. Identify genre preferences
3. Track reading velocity and habits
4. Provide behavioral insights

This agent returns TEXT responses (not HTML) because it's typically
called by other agents for analysis.
"""

from pathlib import Path
from typing import TYPE_CHECKING
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
)
from .base_agent import BaseAgent
from ..tools import list_books, get_stats

if TYPE_CHECKING:
    from .router import AgentRouter

SKILL_PATH = Path(__file__).parent.parent / "skills" / "insights.md"


class InsightsAgent(BaseAgent):
    """Agent specialized in reading pattern analysis."""

    def __init__(self, router: "AgentRouter"):
        super().__init__(router, "insights")
        self.client: ClaudeSDKClient | None = None
        self._connected = False

    def _load_skill_file(self) -> str:
        """Load the insights skill file."""
        if SKILL_PATH.exists():
            return SKILL_PATH.read_text()
        return self._default_skill()

    def _default_skill(self) -> str:
        """Default skill if file doesn't exist."""
        return """# Reading Insights Agent

You are a reading behavior analyst. Your job is to analyze reading patterns
and provide insights about reading habits.

## Your Personality
- Analytical and data-driven
- Curious about reading behavior
- Clear and concise in explanations
- Supportive of reading goals

## How You Work
1. Use list_books to get the full reading list
2. Use get_stats for aggregate statistics
3. Analyze patterns in the data
4. Provide actionable insights

## Types of Analysis
- **Status distribution**: What proportion of books are in each status?
- **Rating patterns**: Do they rate books highly? Are ratings consistent?
- **Reading velocity**: How many books finished vs. in progress?
- **Preference indicators**: Any patterns in titles/authors?

## Response Format
Return structured TEXT analysis (not HTML):

Example response:
"## Reading Pattern Analysis

**Status Breakdown**:
- 40% Want to Read (8 books)
- 15% Currently Reading (3 books)
- 45% Finished (9 books)

**Key Insights**:
1. Strong completion rate - you finish most books you start
2. Average rating of 4.2 suggests selective reading (quality over quantity)
3. Growing backlog of want-to-read books (8) - consider prioritizing

**Recommendations**:
- Your 3 in-progress books may benefit from focus
- Consider reviewing your want-to-read list for priorities"
"""

    def _build_system_prompt(self) -> str:
        """Build complete system prompt."""
        skill_content = self._load_skill_file()
        agent_awareness = self._get_agent_awareness_prompt()

        return f"""{skill_content}

{agent_awareness}

## Important Notes
- You return TEXT responses, not HTML
- You may be called by UI agent or Recommender agent
- Focus on patterns and insights, not specific recommendations
- Be concise but thorough in your analysis
"""

    def _create_mcp_server(self):
        """Create MCP server with analysis tools."""
        from claude_agent_sdk import create_sdk_mcp_server

        message_tool = self._create_message_agent_tool()

        return create_sdk_mcp_server(
            name="insights_tools",
            version="1.0.0",
            tools=[
                list_books,
                get_stats,
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
            mcp_servers={"insights_tools": tools_server},
            allowed_tools=[
                "mcp__insights_tools__list_books",
                "mcp__insights_tools__get_stats",
                "mcp__insights_tools__message_agent",
            ],
            permission_mode="acceptEdits",
        )

        self.client = ClaudeSDKClient(options=options)
        await self.client.connect()
        self._connected = True

    async def process(self, message: str) -> str:
        """Process message and return text analysis."""
        await self._ensure_connected()
        await self.client.query(message)

        text_parts: list[str] = []
        async for msg in self.client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)

        return "\n".join(text_parts).strip()

    async def reset(self):
        """Reset conversation state."""
        if self.client:
            await self.client.disconnect()
            self.client = None
            self._connected = False

    async def close(self):
        """Clean up resources."""
        await self.reset()
