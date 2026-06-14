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
