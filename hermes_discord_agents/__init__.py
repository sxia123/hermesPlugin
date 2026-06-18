"""Discord Agents plugin entry point."""
import asyncio
import logging
import json
from .config import load_config
from .gateway import DiscordGateway

# Set up logging for the Discord plugin
logger = logging.getLogger("hermes.discord_agents")

# Global instances shared across functions and hooks
_gateway = None  # Reference to DiscordGateway instance
_config = None   # Reference to AgentConfig dataclass
_ctx_ref = None  # Reference to the parent Hermes context object

async def handle_incoming_message(message):
    """Callback when a message is received in a watched channel/thread.
    This coordinates checking message origin, building prompt contexts, 
    requesting a reply from Hermes, and sending the response.
    """
    global _ctx_ref, _gateway

    # Step 1: Let bots see each other's messages. Skip user messages and messages from this bot.
    if not message.author.bot:
        return

    logger.info("Received message from bot %s in channel %s: %s", 
                message.author.display_name, message.channel.name, message.content)

    if not _ctx_ref:
        return

    # Step 2: Retrieve the last 10 messages from channel history to form a simple conversation context
    history_context = []
    try:
        async for msg in message.channel.history(limit=10, oldest_first=True):
            history_context.append(f"@{msg.author.display_name}: {msg.content}")
    except Exception as e:
        logger.warning("Failed to fetch history: %s", e)
        # Fall back to logging only the active trigger message if history retrieval fails
        history_context.append(f"@{message.author.display_name}: {message.content}")

    # Step 2b: Simple loop guardrail to prevent bots from repeating messages infinitely
    if len(history_context) >= 2:
        parts = [h.split(": ", 1) for h in history_context[-2:]]
        if len(parts) == 2 and len(parts[0]) == 2 and len(parts[1]) == 2:
            msg1 = parts[0][1].strip().lower()
            msg2 = parts[1][1].strip().lower()
            if msg1 == msg2 and msg1 != "":
                logger.warning("Loop detected (duplicate consecutive messages). Skipping response.")
                return

    history_str = "\n".join(history_context)

    # Step 2c: Retrieve the bot's own name to help it stay in character
    own_name = _gateway.client.user.name if (_gateway and _gateway.client and _gateway.client.user) else "Agent"

    # Step 3: Formulate a system prompt goal to instruct the LLM to generate the next response
    goal = f"""You are a Discord bot named @{own_name} collaborating with other bots in the channel.
Recent channel history:
{history_str}

Respond to the last message from @{message.author.display_name} in the conversation as @{own_name}. Keep your reply direct, concise, and in-character. Do not include user prefixes in your final response text."""

    # Step 4: Define a task wrapper to run asynchronously without blocking the Discord gateway
    async def run_task():
        try:
            # Step 5: Dispatch a delegate task inside a thread to get the next turn's output from the LLM
            result_str = await asyncio.to_thread(
                _ctx_ref.dispatch_tool,
                "delegate_task",
                {
                    "goal": goal,
                    "toolsets": ["discord_agents"]
                }
            )
            # Step 6: Send the generated response text back to the Discord channel
            if result_str:
                await _gateway.send_message(message.channel.id, result_str.strip())
        except Exception as e:
            logger.error("Failed to generate/send response: %s", e)

    # Step 7: Schedule execution of the response generator task
    asyncio.create_task(run_task())

async def agent_send_message(args: dict, **kwargs) -> str:
    """Send a message to a Discord channel/thread.
    Exposed as a tool to the Hermes LLM context.
    
    Args:
        args (dict): Must contain "channel_id" (str) and "message" (str).
        
    Returns:
        str: JSON string indicating success or failure status.
    """
    global _gateway
    channel_id_str = args.get("channel_id", "").strip()
    content = args.get("message", "").strip()

    # Validate arguments
    if not channel_id_str or not content:
        return json.dumps({"error": "Missing channel_id or message"})

    try:
        channel_id = int(channel_id_str)
    except ValueError:
        return json.dumps({"error": "channel_id must be a valid integer string"})

    if not _gateway or not _gateway.client or not _gateway.client.is_ready():
        return json.dumps({"error": "Discord gateway not active"})

    # Forward message via gateway client
    msg_id = await _gateway.send_message(channel_id, content)
    if msg_id:
        return json.dumps({"status": "success", "message_id": msg_id})
    return json.dumps({"error": "Failed to send message"})

def on_session_start_handler(**kwargs):
    """Lifecycle Hook: Triggers when the Hermes session starts.
    Runs the gateway start sequence on the event loop.
    """
    global _gateway
    if _gateway:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_gateway.start())
        except RuntimeError:
            asyncio.run(_gateway.start())

def on_session_end_handler(**kwargs):
    """Lifecycle Hook: Triggers when the Hermes session ends.
    Stops the gateway client and cleans up background tasks.
    """
    global _gateway
    if _gateway:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_gateway.stop())
        except RuntimeError:
            asyncio.run(_gateway.stop())

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
