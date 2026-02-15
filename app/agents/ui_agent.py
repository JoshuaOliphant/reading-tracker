# ABOUTME: UI Agent handles user interaction and HTML generation.
# ABOUTME: Coordinates with Recommender and Insights agents for specialized tasks.

"""
UI Agent - User Interface Specialist

Responsibilities:
1. Receive user messages and interpret intent
2. Generate HTML UI responses
3. Delegate to specialist agents when appropriate:
   - Recommender agent for "what should I read" queries
   - Insights agent for reading pattern analysis
4. Coordinate multi-agent responses into coherent UI
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
from ..tools import create_tools_server

if TYPE_CHECKING:
    from .router import AgentRouter

SKILL_PATH = Path(__file__).parent.parent / "skills" / "ui.md"


class UIAgent(BaseAgent):
    """Agent specialized in user interaction and HTML generation."""

    def __init__(self, router: "AgentRouter"):
        super().__init__(router, "ui")
        self.data_tools_server = create_tools_server()
        self.client: ClaudeSDKClient | None = None
        self._connected = False

    def _load_skill_file(self) -> str:
        """Load the UI skill file."""
        if SKILL_PATH.exists():
            return SKILL_PATH.read_text()
        return ""

    def _build_system_prompt(self) -> str:
        """Build complete system prompt with skill + agent awareness."""
        skill_content = self._load_skill_file()
        agent_awareness = self._get_agent_awareness_prompt()

        return f"""{skill_content}

{agent_awareness}

## Final Reminders

- Output ONLY raw HTML. No markdown. No code fences. No explanations.
- Every interactive element needs hx-post="/agent" and hx-target="#content"
- Use hx-vals to pass the message describing what action to take
- When user asks for recommendations or "what to read next", use message_agent to ask the recommender
- When user asks about reading patterns or insights, use message_agent to ask the insights agent
- When you receive responses from other agents, incorporate them into your HTML response
"""

    def _create_mcp_server(self):
        """Create MCP server with data tools + messaging tool."""
        from claude_agent_sdk import create_sdk_mcp_server
        from ..tools import (
            list_books, get_book, create_book, update_book,
            delete_book, search_books, get_stats
        )

        message_tool = self._create_message_agent_tool()

        return create_sdk_mcp_server(
            name="ui_tools",
            version="1.0.0",
            tools=[
                list_books,
                get_book,
                create_book,
                update_book,
                delete_book,
                search_books,
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
            mcp_servers={"ui_tools": tools_server},
            allowed_tools=[
                "mcp__ui_tools__list_books",
                "mcp__ui_tools__get_book",
                "mcp__ui_tools__create_book",
                "mcp__ui_tools__update_book",
                "mcp__ui_tools__delete_book",
                "mcp__ui_tools__search_books",
                "mcp__ui_tools__get_stats",
                "mcp__ui_tools__message_agent",
            ],
            permission_mode="acceptEdits",
        )

        self.client = ClaudeSDKClient(options=options)
        await self.client.connect()
        self._connected = True

    async def process(self, message: str) -> str:
        """Process user message and return HTML."""
        await self._ensure_connected()
        await self.client.query(message)

        html_parts: list[str] = []
        async for msg in self.client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        html_parts.append(block.text)

        html = "\n".join(html_parts)
        return self._clean_html(html)

    def _clean_html(self, html: str) -> str:
        """Strip markdown fences if present."""
        html = html.strip()
        if html.startswith("```html"):
            html = html[7:]
        elif html.startswith("```"):
            html = html[3:]
        if html.endswith("```"):
            html = html[:-3]
        return html.strip()

    async def reset(self):
        """Reset conversation state."""
        if self.client:
            await self.client.disconnect()
            self.client = None
            self._connected = False

    async def close(self):
        """Clean up resources."""
        await self.reset()
