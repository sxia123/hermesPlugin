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
    assert cfg.soul_path == "./soul.md"
    assert cfg.peer_souls_dir == "./souls"
    assert cfg.thread_history_depth == 200
    assert cfg.max_turns_per_conversation == 10
    assert cfg.context_window_size == 20
    assert cfg.summarize_after == 10
    assert cfg.enable_logging is True
    assert cfg.loop_detection_threshold == 3

def test_config_loading():
    with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".yaml") as f:
        f.write("""
discord_agents:
  bot_token: "test_token"
  watch_channels:
    - "agent-dev"
  thread_history_depth: 50
  loop_detection_threshold: 5
""")
        temp_name = f.name

    try:
        cfg = load_config(Path(temp_name))
        assert cfg.bot_token == "test_token"
        assert cfg.watch_channels == ["agent-dev"]
        assert cfg.thread_history_depth == 50
        assert cfg.loop_detection_threshold == 5
    finally:
        os.unlink(temp_name)

def test_config_loading_dotenv(tmp_path, monkeypatch):
    """Uses tmp_path so the .env file never touches the real CWD."""
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text("DISCORD_BOT_TOKEN=dotenv_token\n", encoding="utf-8")

    cfg = load_config()
    assert cfg.bot_token == "dotenv_token"

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
async def test_loop_guardrail_default_threshold():
    """Loop guardrail triggers when 3 (default threshold) consecutive messages match."""
    import hermes_discord_agents
    
    # Mock message
    mock_msg = MagicMock()
    mock_msg.author.bot = True
    mock_msg.author.display_name = "OtherBot"
    mock_msg.content = "Repeat this"
    mock_msg.channel.name = "agent-dev"
    
    # Mock history returns 3 duplicate messages (matches default threshold=3)
    duplicates = []
    for _ in range(3):
        m = MagicMock()
        m.author.display_name = "OtherBot"
        m.content = "Repeat this"
        duplicates.append(m)
    
    async def mock_history(limit, oldest_first):
        for d in duplicates:
            yield d
        
    mock_msg.channel.history = mock_history
    
    # Mock gateway and config
    mock_gateway = MagicMock()
    mock_gateway.client = MagicMock()
    mock_gateway.client.user.name = "MyBot"
    
    mock_config = AgentConfig(loop_detection_threshold=3)
    mock_ctx = MagicMock()
    
    hermes_discord_agents._gateway = mock_gateway
    hermes_discord_agents._ctx_ref = mock_ctx
    hermes_discord_agents._config = mock_config
    
    # Run callback
    await hermes_discord_agents.handle_incoming_message(mock_msg)
    
    # Verify delegate task was NOT called because loop guardrail should return early
    mock_ctx.dispatch_tool.assert_not_called()

@pytest.mark.asyncio
async def test_loop_guardrail_normalized():
    """Loop guardrail catches duplicates that differ only by punctuation."""
    import hermes_discord_agents
    
    mock_msg = MagicMock()
    mock_msg.author.bot = True
    mock_msg.author.display_name = "OtherBot"
    mock_msg.content = "Hello!"
    mock_msg.channel.name = "agent-dev"
    
    msgs = []
    for text in ["Hello", "Hello!", "hello..."]:
        m = MagicMock()
        m.author.display_name = "OtherBot"
        m.content = text
        msgs.append(m)
    
    async def mock_history(limit, oldest_first):
        for m in msgs:
            yield m
        
    mock_msg.channel.history = mock_history
    
    mock_gateway = MagicMock()
    mock_gateway.client = MagicMock()
    mock_gateway.client.user.name = "MyBot"
    
    mock_config = AgentConfig(loop_detection_threshold=3)
    mock_ctx = MagicMock()
    
    hermes_discord_agents._gateway = mock_gateway
    hermes_discord_agents._ctx_ref = mock_ctx
    hermes_discord_agents._config = mock_config
    
    await hermes_discord_agents.handle_incoming_message(mock_msg)
    
    # All three normalize to "hello" — loop should be detected
    mock_ctx.dispatch_tool.assert_not_called()
