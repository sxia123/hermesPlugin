"""Discord Agents plugin entry point."""
import asyncio
import logging
import json
import re
from .config import load_config
from .gateway import DiscordGateway

# Set up logging for the Discord plugin
logger = logging.getLogger("hermes.discord_agents")

# Global instances shared across functions and hooks
_gateway = None  # Reference to DiscordGateway instance
_config = None   # Reference to AgentConfig dataclass
_ctx_ref = None  # Reference to the parent Hermes context object
_lock = asyncio.Lock()  # Guards access to the mutable globals above
_pending_tasks: set[asyncio.Task] = set()  # Prevents GC of fire-and-forget tasks

# Regex that strips punctuation and collapses whitespace for fuzzy comparison
_NORMALIZE_RE = re.compile(r"[^\w\s]")

def _normalize_text(text: str) -> str:
    """Lowercase, strip punctuation, and collapse whitespace for comparison."""
    return _NORMALIZE_RE.sub("", text).strip().lower()

async def handle_incoming_message(message):
    """Callback when a message is received in a watched channel/thread.
    This coordinates checking message origin, building prompt contexts, 
    requesting a reply from Hermes, and sending the response.
    """
    # Step 1: Let bots see each other's messages. Skip user messages and messages from this bot.
    if not message.author.bot:
        return

    logger.info("Received message from bot %s in channel %s: %s", 
                message.author.display_name, message.channel.name, message.content)

    async with _lock:
        ctx_ref = _ctx_ref
        gateway = _gateway
        config = _config

    if not ctx_ref or not gateway or not config:
        return

    # Step 2: Retrieve recent messages from channel history to form conversation context
    history_depth = config.thread_history_depth if config.thread_history_depth else 200
    history_context = []
    try:
        async for msg in message.channel.history(limit=history_depth, oldest_first=True):
            history_context.append(f"@{msg.author.display_name}: {msg.content}")
    except Exception as e:
        logger.warning("Failed to fetch history: %s", e)
        # Fall back to logging only the active trigger message if history retrieval fails
        history_context.append(f"@{message.author.display_name}: {message.content}")

    # Step 3: Loop guardrail — check last N messages for duplicate content
    threshold = config.loop_detection_threshold if config.loop_detection_threshold >= 2 else 3
    if len(history_context) >= threshold:
        tail = history_context[-threshold:]
        normalized = []
        for entry in tail:
            parts = entry.split(": ", 1)
            body = _normalize_text(parts[1]) if len(parts) == 2 else ""
            normalized.append(body)
        if normalized[0] and all(n == normalized[0] for n in normalized):
            logger.warning(
                "Loop detected (%d consecutive duplicate messages). Skipping response.",
                threshold,
            )
            return

    history_str = "\n".join(history_context)

    # Step 4: Retrieve the bot's own name to help it stay in character
    own_name = gateway.client.user.name if (gateway.client and gateway.client.user) else "Agent"

    # Step 5: Formulate a system prompt goal to instruct the LLM to generate the next response
    goal = f"""You are a Discord bot named @{own_name} collaborating with other bots in the channel.
Recent channel history:
{history_str}

Respond to the last message from @{message.author.display_name} in the conversation as @{own_name}. Keep your reply direct, concise, and in-character. Do not include user prefixes in your final response text."""

    # Step 6: Define a task wrapper to run asynchronously without blocking the Discord gateway
    async def run_task():
        try:
            # Dispatch a delegate task inside a thread to get the next turn's output from the LLM
            result_str = await asyncio.to_thread(
                ctx_ref.dispatch_tool,
                "delegate_task",
                {
                    "goal": goal,
                    "toolsets": ["discord_agents"]
                }
            )
            # Send the generated response text back to the Discord channel
            if result_str:
                await gateway.send_message(message.channel.id, result_str.strip())
        except Exception as e:
            logger.error("Failed to generate/send response: %s", e)

    # Step 7: Schedule execution and retain a reference to prevent GC
    task = asyncio.create_task(run_task())
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)

async def agent_send_message(args: dict, **kwargs) -> str:
    """Send a message to a Discord channel/thread.
    Exposed as a tool to the Hermes LLM context.
    
    Args:
        args (dict): Must contain "channel_id" (str) and "message" (str).
        
    Returns:
        str: JSON string indicating success or failure status.
    """
    channel_id_str = args.get("channel_id", "").strip()
    content = args.get("message", "").strip()

    # Validate arguments
    if not channel_id_str or not content:
        return json.dumps({"error": "Missing channel_id or message"})

    try:
        channel_id = int(channel_id_str)
    except ValueError:
        return json.dumps({"error": "channel_id must be a valid integer string"})

    async with _lock:
        gateway = _gateway

    if not gateway or not gateway.client or not gateway.client.is_ready():
        return json.dumps({"error": "Discord gateway not active"})

    # Forward message via gateway client
    msg_id = await gateway.send_message(channel_id, content)
    if msg_id:
        return json.dumps({"status": "success", "message_id": msg_id})
    return json.dumps({"error": "Failed to send message"})


async def _start_gateway():
    """Async helper to start the gateway safely."""
    async with _lock:
        gateway = _gateway
    if gateway:
        await gateway.start()


async def _stop_gateway():
    """Async helper to stop the gateway safely."""
    async with _lock:
        gateway = _gateway
    if gateway:
        await gateway.stop()


def _schedule_async(coro):
    """Schedule a coroutine onto the running event loop, with a sync fallback.
    
    If a running loop exists, creates a task on it.
    If no loop is running (pure sync context), spins up a new loop in the current thread.
    """
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        _pending_tasks.add(task)
        task.add_done_callback(_pending_tasks.discard)
    except RuntimeError:
        # No running loop — we're in a purely synchronous context
        asyncio.run(coro)


def on_session_start_handler(**kwargs):
    """Lifecycle Hook: Triggers when the Hermes session starts.
    Runs the gateway start sequence on the event loop.
    """
    _schedule_async(_start_gateway())


def on_session_end_handler(**kwargs):
    """Lifecycle Hook: Triggers when the Hermes session ends.
    Stops the gateway client and cleans up background tasks.
    """
    _schedule_async(_stop_gateway())


def register(ctx):
    """Entry point for Hermes plugin registration.
    Loads settings, instantiates gateway client, and registers tools and hooks.
    """
    global _gateway, _config, _ctx_ref
    _ctx_ref = ctx
    
    # Load token and watched channel list
    _config = load_config()
    
    # Initialize the client gateway with config and incoming message handler
    _gateway = DiscordGateway(_config, handle_incoming_message)
    
    # Register the message-sending tool so the LLM can use it
    ctx.register_tool(
        name="agent_send_message",
        toolset="discord_agents",
        schema={
            "name": "agent_send_message",
            "description": "Send a message to a Discord channel or thread ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel_id": {"type": "string", "description": "The Discord channel or thread ID."},
                    "message": {"type": "string", "description": "The message content to send."}
                },
                "required": ["channel_id", "message"]
            }
        },
        handler=agent_send_message
    )

    # Register start and stop event hook handlers
    ctx.register_hook("on_session_start", on_session_start_handler)
    ctx.register_hook("on_session_end", on_session_end_handler)
    logger.info("Hermes Discord Agents plugin (minimal) registered.")
