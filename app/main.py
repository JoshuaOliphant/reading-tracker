# ABOUTME: FastAPI application serving as the HTTP adapter for the multi-agent system.
# ABOUTME: Routes user messages through AgentRouter, with saved views for faster responses.

"""
FastAPI application - HTTP adapter for the multi-agent hexagonal pattern.

Responsibilities:
1. Serve the base HTML template
2. Check for saved views before calling agents (fast path)
3. Handle /agent POST requests via AgentRouter (slow path)
4. Allow users to save views they like
5. Provide debug endpoints for messages and views
"""

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from contextlib import asynccontextmanager
from typing import Optional
import html as html_escape
import json

from app.agents import AgentRouter
from app.saved_views import (
    get_views_manager,
    render_data_driven_view,
    render_book_list_html,
    ViewType,
)
from app import database as db

router = AgentRouter()
views_manager = get_views_manager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - init database and cleanup on shutdown."""
    # Initialize database and migrate from JSON if needed
    await db.init_db()
    await db.migrate_from_json()
    yield
    await router.close()


app = FastAPI(lifespan=lifespan)


BASE_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Reading List</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=Inter:wght@400;500&display=swap" rel="stylesheet">
    <style>
        .loading-indicator.htmx-request {{ display: flex !important; }}
        .loading-indicator {{ display: none; }}
        @keyframes fadeSlideIn {{
            from {{ opacity: 0; transform: translateY(8px); }}
            to {{ opacity: 1; transform: translateY(0); }}
        }}
        .animate-in {{ animation: fadeSlideIn 0.3s ease-out; }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}
        .animate-pulse {{ animation: pulse 1.5s ease-in-out infinite; }}
        @keyframes bounce {{
            0%, 100% {{ transform: translateY(0); }}
            50% {{ transform: translateY(-4px); }}
        }}
        .agent-dot {{ animation: bounce 0.6s ease-in-out infinite; }}
        .agent-dot:nth-child(2) {{ animation-delay: 0.1s; }}
        .agent-dot:nth-child(3) {{ animation-delay: 0.2s; }}
        .htmx-request .htmx-indicator {{ display: inline !important; }}
        .htmx-request .htmx-indicator-hide {{ display: none !important; }}
        .htmx-indicator {{ display: none; }}
    </style>
</head>
<body class="min-h-screen bg-slate-950 text-slate-100">
    <nav class="bg-slate-900 border-b border-slate-800">
        <div class="max-w-4xl mx-auto px-4 py-3 flex justify-between items-center">
            <h1 class="text-xl font-bold font-['Space_Grotesk']">Reading List</h1>
            <div class="flex items-center gap-4">
                <button hx-get="/views/list" hx-target="#content"
                        class="text-sm text-purple-400 hover:text-purple-300 transition-colors flex items-center gap-1">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                              d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/>
                    </svg>
                    Saved Views
                </button>
                <button hx-get="/activity" hx-target="#content"
                        class="text-sm text-indigo-400 hover:text-indigo-300 transition-colors flex items-center gap-1">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                              d="M13 10V3L4 14h7v7l9-11h-7z"/>
                    </svg>
                    Activity
                </button>
                <a href="/debug/messages" target="_blank"
                   class="text-xs text-slate-500 hover:text-slate-400 transition-colors">
                    Debug
                </a>
                <button hx-post="/reset" hx-target="#content"
                        class="text-sm text-slate-400 hover:text-white transition-colors">
                    Reset
                </button>
            </div>
        </div>
    </nav>

    <main class="max-w-4xl mx-auto p-4">
        <div class="loading-indicator flex-col items-center justify-center py-12">
            <div class="bg-slate-900 rounded-xl border border-slate-700 p-6 shadow-xl shadow-indigo-500/10">
                <div class="flex items-center justify-center gap-3 mb-4">
                    <svg class="animate-spin h-6 w-6 text-indigo-500" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                    </svg>
                    <span class="text-white font-medium">Agents Working</span>
                </div>
                <div class="flex items-center justify-center gap-2 text-sm">
                    <span class="agent-dot w-2 h-2 bg-indigo-400 rounded-full"></span>
                    <span class="agent-dot w-2 h-2 bg-purple-400 rounded-full"></span>
                    <span class="agent-dot w-2 h-2 bg-pink-400 rounded-full"></span>
                </div>
                <p class="text-slate-400 text-sm mt-3 text-center animate-pulse">
                    Processing your request...
                </p>
            </div>
        </div>

        <div id="content">
            {content}
        </div>
    </main>

    <footer class="fixed bottom-0 left-0 right-0 bg-slate-900 border-t border-slate-800">
        <form hx-post="/agent" hx-target="#content" hx-indicator=".loading-indicator" class="max-w-4xl mx-auto p-4 flex gap-3">
            <input type="text" name="message"
                   placeholder="What would you like to do?"
                   autocomplete="off"
                   class="flex-1 px-4 py-2 bg-slate-800 border border-slate-700 rounded-lg
                          text-white placeholder-slate-500
                          focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent
                          disabled:opacity-50 disabled:cursor-not-allowed"
                   hx-disabled-elt="this">
            <button type="submit"
                    class="px-6 py-2 bg-indigo-600 hover:bg-indigo-500
                           text-white font-medium rounded-lg transition-colors
                           disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-indigo-600"
                    hx-disabled-elt="this">
                <span class="htmx-indicator-hide">Send</span>
                <span class="htmx-indicator hidden">
                    <svg class="animate-spin h-5 w-5 inline" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                    </svg>
                </span>
            </button>
        </form>
    </footer>

    <div class="h-24"></div>

    <script>
        // Loading messages that cycle during agent processing
        const loadingMessages = [
            "Processing your request...",
            "UI Agent analyzing intent...",
            "Consulting specialist agents...",
            "Generating response...",
            "Almost there..."
        ];
        let messageIndex = 0;
        let messageInterval = null;

        document.body.addEventListener('htmx:beforeRequest', function(event) {{
            // Show loading indicator for all requests
            const indicator = document.querySelector('.loading-indicator');
            const content = document.getElementById('content');
            if (indicator) {{
                indicator.style.display = 'flex';
            }}
            if (content) {{
                content.style.opacity = '0.3';
                content.style.pointerEvents = 'none';
                content.style.filter = 'blur(1px)';
            }}

            // Start cycling through loading messages
            const loadingText = document.querySelector('.loading-indicator .animate-pulse');
            if (loadingText) {{
                messageIndex = 0;
                loadingText.textContent = loadingMessages[0];
                messageInterval = setInterval(() => {{
                    messageIndex = (messageIndex + 1) % loadingMessages.length;
                    loadingText.textContent = loadingMessages[messageIndex];
                }}, 1500);
            }}
        }});

        document.body.addEventListener('htmx:afterRequest', function(event) {{
            // Hide loading indicator
            const indicator = document.querySelector('.loading-indicator');
            const content = document.getElementById('content');
            if (indicator) {{
                indicator.style.display = 'none';
            }}
            if (content) {{
                content.style.opacity = '1';
                content.style.pointerEvents = 'auto';
                content.style.filter = 'none';
            }}

            // Stop the message cycling
            if (messageInterval) {{
                clearInterval(messageInterval);
                messageInterval = null;
            }}

            // Clear form input
            if (event.detail.elt.matches('form')) {{
                const input = event.detail.elt.querySelector('input[name="message"]');
                if (input) input.value = '';
            }}
        }});

        document.querySelector('input[name="message"]')?.focus();

        // Save view modal functionality
        // Note: innerHTML is used here with server-generated content (agent output),
        // not untrusted user input. This is safe for our internal experimental use.
        function showSaveModal(triggerPhrase) {{
            const modal = document.getElementById('save-modal');
            const triggerInput = document.getElementById('save-trigger');
            const contentDiv = document.getElementById('content');

            triggerInput.value = triggerPhrase;
            document.getElementById('save-html').value = contentDiv.innerHTML;
            modal.classList.remove('hidden');
        }}

        function closeSaveModal() {{
            document.getElementById('save-modal').classList.add('hidden');
        }}

        function submitSaveView() {{
            const form = document.getElementById('save-view-form');
            const formData = new FormData(form);

            fetch('/views/save', {{
                method: 'POST',
                body: formData
            }})
            .then(response => response.text())
            .then(html => {{
                document.getElementById('content').innerHTML = html;
                closeSaveModal();
            }})
            .catch(err => console.error('Save failed:', err));
        }}
    </script>

    <!-- Save View Modal -->
    <div id="save-modal" class="hidden fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50">
        <div class="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-md mx-4 animate-in">
            <div class="p-5 border-b border-slate-800">
                <h3 class="text-lg font-bold font-['Space_Grotesk'] text-white">Save This View</h3>
                <p class="text-slate-400 text-sm mt-1">Save for instant access next time</p>
            </div>
            <form id="save-view-form" class="p-5 space-y-4">
                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-2">View Name</label>
                    <input type="text" name="name" required placeholder="e.g., My Book List"
                           class="w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white
                                  placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500">
                </div>
                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-2">Trigger Phrase</label>
                    <input type="text" name="trigger_phrase" id="save-trigger" required
                           class="w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white
                                  placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500">
                    <p class="text-xs text-slate-500 mt-1">Type this exactly to load this view instantly</p>
                </div>
                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-2">Keywords (optional)</label>
                    <input type="text" name="keywords" placeholder="books, list, reading"
                           class="w-full px-4 py-2.5 bg-slate-800 border border-slate-700 rounded-lg text-white
                                  placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500">
                    <p class="text-xs text-slate-500 mt-1">Comma-separated words that should trigger this view</p>
                </div>
                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-2">View Type</label>
                    <div class="space-y-2">
                        <label class="flex items-start gap-3 p-3 bg-slate-800 rounded-lg cursor-pointer hover:bg-slate-700 transition-colors">
                            <input type="radio" name="view_type" value="static" checked
                                   class="mt-1 w-4 h-4 text-indigo-600 focus:ring-indigo-500">
                            <div>
                                <p class="text-white font-medium">Static</p>
                                <p class="text-xs text-slate-400">For forms, welcome screens. Caches exact HTML.</p>
                            </div>
                        </label>
                        <label class="flex items-start gap-3 p-3 bg-slate-800 rounded-lg cursor-pointer hover:bg-slate-700 transition-colors">
                            <input type="radio" name="view_type" value="data-driven"
                                   class="mt-1 w-4 h-4 text-indigo-600 focus:ring-indigo-500">
                            <div>
                                <p class="text-white font-medium">Data-driven</p>
                                <p class="text-xs text-slate-400">For book lists. Uses template + fetches fresh data.</p>
                            </div>
                        </label>
                    </div>
                </div>
                <input type="hidden" name="html_template" id="save-html">
            </form>
            <div class="p-5 border-t border-slate-800 flex justify-end gap-3">
                <button onclick="closeSaveModal()"
                        class="px-4 py-2 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors">
                    Cancel
                </button>
                <button onclick="submitSaveView()"
                        class="px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white font-medium rounded-lg
                               shadow-lg shadow-indigo-500/25 transition-all">
                    Save View
                </button>
            </div>
        </div>
    </div>
</body>
</html>'''


WELCOME_CONTENT = '''
<div class="text-center py-16 animate-in">
    <div class="w-20 h-20 rounded-2xl bg-gradient-to-br from-indigo-600 to-purple-600 flex items-center justify-center mx-auto mb-6 shadow-lg shadow-indigo-500/30">
        <span class="text-4xl">📚</span>
    </div>
    <h2 class="text-3xl font-bold font-['Space_Grotesk'] text-white mb-4">Welcome to Your Reading List</h2>
    <p class="text-slate-400 mb-8 max-w-md mx-auto">Track the books you want to read, are reading, and have finished. Rate and review your favorites!</p>

    <div class="mb-8 p-4 bg-slate-900/50 rounded-xl border border-slate-800 max-w-lg mx-auto">
        <p class="text-sm text-purple-400 mb-2">🤖 Multi-Agent System</p>
        <p class="text-xs text-slate-500">UI Agent • Recommender Agent • Insights Agent</p>
    </div>

    <div class="flex flex-wrap justify-center gap-4">
        <button hx-post="/agent" hx-target="#content" hx-indicator=".loading-indicator" hx-vals='{"message":"show my books"}'
                class="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg transition-colors font-medium">
            📖 View My Books
        </button>
        <button hx-post="/agent" hx-target="#content" hx-indicator=".loading-indicator" hx-vals='{"message":"add a book"}'
                class="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 rounded-lg transition-colors font-medium shadow-lg shadow-indigo-500/25">
            + Add a Book
        </button>
        <button hx-post="/agent" hx-target="#content" hx-indicator=".loading-indicator" hx-vals='{"message":"what should I read next"}'
                class="px-5 py-2.5 bg-purple-600 hover:bg-purple-500 rounded-lg transition-colors font-medium shadow-lg shadow-purple-500/25">
            🎯 Get Recommendations
        </button>
        <button hx-post="/agent" hx-target="#content" hx-indicator=".loading-indicator" hx-vals='{"message":"analyze my reading patterns"}'
                class="px-5 py-2.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg transition-colors font-medium">
            📊 Reading Insights
        </button>
    </div>
</div>
'''


@app.get("/", response_class=HTMLResponse)
async def home():
    """Serve the main page."""
    return BASE_TEMPLATE.format(content=WELCOME_CONTENT)


@app.post("/agent", response_class=HTMLResponse)
async def handle_message(request: Request):
    """Handle user messages via the AgentRouter.

    Fast path: Check for saved views first.
    Slow path: Fall back to agent processing.
    """
    form_data = await request.form()

    message = form_data.get("message", "")
    if not message or not str(message).strip():
        return '<p class="text-amber-400">Please enter a message.</p>'

    message = str(message).strip()

    # FAST PATH: Check for saved view match
    saved_view = views_manager.find_matching_view(message)
    if saved_view:
        if saved_view.is_static:
            # Static view: serve directly
            return saved_view.html_template
        else:
            # Data-driven view: fetch fresh data and render template
            books = await db.get_all_books()
            html = await render_data_driven_view(saved_view, {"books": books})
            return html

    # SLOW PATH: Append form fields to message and call agent
    extra_fields = []
    for key, value in form_data.items():
        if key != "message" and value:
            extra_fields.append(f"{key}={value}")

    if extra_fields:
        message = f"{message} [{', '.join(extra_fields)}]"

    try:
        html = await router.process_user_message(message)
        # Wrap response with save option
        html = _wrap_with_save_option(html, message)
        return html
    except Exception as e:
        print(f"Agent error: {e}")
        import traceback
        traceback.print_exc()
        return '''
<div class="p-4 bg-red-500/10 border border-red-500/30 rounded-lg">
    <p class="text-red-300">An error occurred. Please try again.</p>
</div>
'''


def _wrap_with_save_option(html: str, original_message: str) -> str:
    """Wrap agent-generated HTML with a save button."""
    escaped_message = html_escape.escape(original_message)
    save_button = f'''
<div class="mt-4 pt-4 border-t border-slate-800 flex justify-end">
    <button onclick="showSaveModal('{escaped_message}')"
            class="text-xs text-slate-500 hover:text-slate-300 transition-colors flex items-center gap-1">
        <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/>
        </svg>
        Save this view
    </button>
</div>
'''
    return html + save_button


@app.post("/reset", response_class=HTMLResponse)
async def reset():
    """Reset all agents and return to welcome screen."""
    await router.reset()
    return WELCOME_CONTENT


@app.get("/debug/messages", response_class=JSONResponse)
async def debug_messages():
    """
    Debug endpoint to view inter-agent message log.
    Useful for testing the message-passing paradigm.
    """
    log = router.get_message_log()
    return {
        "total_messages": len(log.messages),
        "messages": [m.to_dict() for m in log.messages]
    }


@app.get("/debug/agents", response_class=JSONResponse)
async def debug_agents():
    """Debug endpoint to view available agents."""
    return {
        "agents": router.get_agent_names(),
        "descriptions": router.get_agent_descriptions()
    }


@app.get("/debug/events", response_class=JSONResponse)
async def debug_events(topic: str = "books", limit: int = 50):
    """
    Debug endpoint to view any brooklet topic.

    Default topic is "books"; pass ?topic=agent.messages to see inter-agent
    traffic, or ?topic=<name> for any other registered topic. Uses a throwaway
    consumer group so polling is safe.
    """
    from app import events as app_events
    stream = app_events.get_stream()
    return {
        "topic": topic,
        "all_topics": list(stream.topics()),
        "events": app_events.read_recent(topic, limit=limit),
    }


@app.get("/activity", response_class=HTMLResponse)
async def activity_feed():
    """User-facing activity feed. Returns an HTMX-swappable fragment."""
    from app import activity
    return activity.render_activity_feed()


@app.post("/views/save", response_class=HTMLResponse)
async def save_view(request: Request):
    """Save the current view for faster future access."""
    form_data = await request.form()
    name = str(form_data.get("name", "")).strip()
    trigger_phrase = str(form_data.get("trigger_phrase", "")).strip()
    keywords = str(form_data.get("keywords", "")).strip()
    html_template = str(form_data.get("html_template", "")).strip()
    view_type = str(form_data.get("view_type", "static")).strip()

    if not name or not trigger_phrase or not html_template:
        return '''
<div class="p-4 bg-amber-500/10 border border-amber-500/30 rounded-lg">
    <p class="text-amber-300">Please provide a name, trigger phrase, and HTML template.</p>
</div>
'''

    # Parse keywords
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]

    if view_type == "data-driven":
        # For data-driven views, convert the HTML to a template
        # Replace the book list section with a placeholder
        template = _convert_to_template(html_template)
        view = views_manager.add_data_driven_view(
            name=name,
            trigger_phrases=[trigger_phrase],
            keywords=keyword_list,
            html_template=template,
            tools_needed=["list_books"],
        )
        view_type_label = "data-driven (always fresh)"
    else:
        view = views_manager.add_static_view(
            name=name,
            trigger_phrases=[trigger_phrase],
            keywords=keyword_list,
            html=html_template,
        )
        view_type_label = "static (cached)"

    return f'''
<div class="p-4 bg-emerald-500/10 border border-emerald-500/30 rounded-lg animate-in">
    <div class="flex items-center gap-3">
        <div class="w-8 h-8 rounded-full bg-emerald-500/20 flex items-center justify-center">
            <span class="text-emerald-400">✓</span>
        </div>
        <div>
            <p class="text-emerald-300 font-medium">View saved!</p>
            <p class="text-slate-400 text-sm">"{name}" ({view_type_label}) will load when you type "{trigger_phrase}"</p>
        </div>
    </div>
</div>
'''


def _convert_to_template(html: str) -> str:
    """
    Convert agent-generated HTML to a template with placeholders.

    This extracts the layout structure and replaces the book list
    with {{BOOK_LIST}} placeholder.
    """
    import re

    # Try to find and replace the book list div
    # Pattern: <div class="space-y-3">...book items...</div>
    pattern = r'<div class="space-y-3">.*?</div>\s*(?=<div class="mt-4|$)'

    if re.search(pattern, html, re.DOTALL):
        template = re.sub(pattern, '{{BOOK_LIST}}\n', html, flags=re.DOTALL)
    else:
        # Fallback: append placeholder at end
        template = html + '\n{{BOOK_LIST}}'

    # Replace hardcoded book count with placeholder
    template = re.sub(r'\d+ books? total', '{{BOOK_COUNT}} books total', template)

    return template


@app.get("/views/list", response_class=HTMLResponse)
async def list_views():
    """List all saved views."""
    views = views_manager.list_views()

    if not views:
        return '''
<div class="text-center py-12 animate-in">
    <div class="w-16 h-16 rounded-2xl bg-slate-800 flex items-center justify-center mx-auto mb-4">
        <span class="text-2xl">📑</span>
    </div>
    <h3 class="text-lg font-semibold text-white mb-2">No saved views yet</h3>
    <p class="text-slate-400 mb-6">Interact with the app and save views you like for instant access.</p>
</div>
'''

    view_items = ""
    for view in views:
        trigger = html_escape.escape(view.trigger_phrases[0] if view.trigger_phrases else "")
        type_badge = '<span class="ml-2 text-xs px-2 py-0.5 bg-indigo-500/20 text-indigo-300 rounded">data-driven</span>' if view.is_data_driven else '<span class="ml-2 text-xs px-2 py-0.5 bg-slate-700 text-slate-400 rounded">static</span>'
        view_items += f'''
<div class="group flex items-center justify-between p-4 bg-slate-900 rounded-lg border border-slate-800
            hover:border-slate-700 hover:bg-slate-800/50 transition-all duration-200">
    <div hx-get="/views/load/{view.id}" hx-target="#content"
         class="flex items-center gap-4 flex-1 cursor-pointer">
        <div class="w-10 h-10 rounded-lg bg-purple-600/20 flex items-center justify-center">
            <span class="text-purple-400 font-semibold">📑</span>
        </div>
        <div>
            <p class="font-medium text-white group-hover:text-purple-300 transition-colors">
                {html_escape.escape(view.name)}{type_badge}
            </p>
            <p class="text-sm text-slate-400">Trigger: "{trigger}"</p>
            <p class="text-xs text-slate-500">Used {view.use_count} times</p>
        </div>
    </div>
    <button hx-post="/views/delete" hx-target="#content"
            hx-vals='{{"view_id": "{view.id}"}}'
            class="text-slate-400 hover:text-red-400 transition-colors p-2 ml-2">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
        </svg>
    </button>
</div>
'''

    return f'''
<div class="animate-in">
    <div class="flex justify-between items-center mb-6">
        <div>
            <h2 class="text-xl font-bold font-['Space_Grotesk'] text-white">Saved Views</h2>
            <p class="text-slate-400 text-sm mt-1">{len(views)} view(s) saved</p>
        </div>
        <button hx-post="/agent" hx-target="#content" hx-vals='{{"message":"show my books"}}'
                class="text-sm text-slate-400 hover:text-white transition-colors">
            ← Back to books
        </button>
    </div>
    <div class="space-y-3">
        {view_items}
    </div>
</div>
'''


@app.get("/views/load/{view_id}", response_class=HTMLResponse)
async def load_view(view_id: str):
    """Load a saved view, fetching fresh data for data-driven views."""
    view = views_manager.get_view(view_id)
    if not view:
        return '<p class="text-red-400">View not found.</p>'

    # Record usage
    views_manager.record_use(view_id)

    if view.is_static:
        return view.html_template
    else:
        # Data-driven: fetch fresh data and render
        books = await db.get_all_books()
        html = await render_data_driven_view(view, {"books": books})
        return html


@app.post("/views/delete", response_class=HTMLResponse)
async def delete_view(request: Request):
    """Delete a saved view."""
    form_data = await request.form()
    view_id = str(form_data.get("view_id", "")).strip()

    if not view_id:
        return '<p class="text-red-400">No view ID provided.</p>'

    deleted = views_manager.delete_view(view_id)
    if deleted:
        # Return updated list
        return await list_views()
    else:
        return '<p class="text-red-400">View not found.</p>'


@app.get("/debug/views", response_class=JSONResponse)
async def debug_views():
    """Debug endpoint to view saved views."""
    views = views_manager.list_views()
    return {
        "total_views": len(views),
        "views": [v.to_dict() for v in views]
    }
