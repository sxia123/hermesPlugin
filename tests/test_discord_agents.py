import os
import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from hermes_discord_agents.config import AgentConfig, load_config
from hermes_discord_agents import agent_send_message

def test_config_defaults():
    cfg = AgentConfig()
    assert cfg.watch_channels == []
    assert cfg.bot_token == ""

def test_config_loading():
    with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".yaml") as f:
        f.write("""
discord_agents:
  bot_token: "test_token"
  watch_channels:
    - "agent-dev"
""")
        temp_name = f.name

    try:
        cfg = load_config(Path(temp_name))
        assert cfg.bot_token == "test_token"
        assert cfg.watch_channels == ["agent-dev"]
    finally:
        os.unlink(temp_name)

def test_config_loading_dotenv():
    # Write temporary .env file
    with open(".env", "w", encoding="utf-8") as f:
        f.write("DISCORD_BOT_TOKEN=dotenv_token\n")
    
    try:
        cfg = load_config()
        assert cfg.bot_token == "dotenv_token"
    finally:
        if os.path.exists(".env"):
            os.remove(".env")

def test_config_loading_env():
    os.environ["DISCORD_BOT_TOKEN"] = "env_token"
    try:
        cfg = load_config()
        assert cfg.bot_token == "env_token"
    finally:
        del os.environ["DISCORD_BOT_TOKEN"]

@pytest.mark.asyncio
async def test_gateway_send_message():
    from hermes_discord_agents.gateway import DiscordGateway
    
    cfg = AgentConfig()
    gateway = DiscordGateway(cfg, on_message_callback=lambda x: None)
    
    gateway.client = MagicMock()
    channel = AsyncMock()
    gateway.client.get_channel = MagicMock(return_value=channel)
    
    await gateway.send_message(123, "Hello World")
    channel.send.assert_called_once_with("Hello World")

@pytest.mark.asyncio
async def test_tool_send_message():
    import hermes_discord_agents
    
    # Mock gateway
    mock_gateway = MagicMock()
    mock_gateway.client = MagicMock()
    mock_gateway.client.is_ready.return_value = True
    mock_gateway.send_message = AsyncMock(return_value="msg-123")
    
    hermes_discord_agents._gateway = mock_gateway
    
    args = {"channel_id": "456", "message": "Test Message"}
    result_str = await agent_send_message(args)
    result = json.loads(result_str)
    
    assert result["status"] == "success"
    assert result["message_id"] == "msg-123"
    mock_gateway.send_message.assert_called_once_with(456, "Test Message")

@pytest.mark.asyncio
async def test_loop_guardrail():
    import hermes_discord_agents
    
    # Mock message
    mock_msg = MagicMock()
    mock_msg.author.bot = True
    mock_msg.author.display_name = "OtherBot"
    mock_msg.content = "Repeat this"
    mock_msg.channel.name = "agent-dev"
    
    # Mock history returns duplicate messages
    msg1 = MagicMock()
    msg1.author.display_name = "OtherBot"
    msg1.content = "Repeat this"
    msg2 = MagicMock()
    msg2.author.display_name = "OtherBot"
    msg2.content = "Repeat this"
    
    async def mock_history(limit, oldest_first):
        yield msg1
        yield msg2
        
    mock_msg.channel.history = mock_history
    
    # Mock gateway
    mock_gateway = MagicMock()
    mock_gateway.client = MagicMock()
    mock_gateway.client.user.name = "MyBot"
    
    # Mock Hermes context reference
    mock_ctx = MagicMock()
    
    hermes_discord_agents._gateway = mock_gateway
    hermes_discord_agents._ctx_ref = mock_ctx
    
    # Run callback
    await hermes_discord_agents.handle_incoming_message(mock_msg)
    
    # Verify delegate task was NOT called because loop guardrail should return early
    mock_ctx.dispatch_tool.assert_not_called()
