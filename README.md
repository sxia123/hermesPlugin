# Hermes Discord Agents (Minimal Plugin)

A minimal, lightweight Discord plugin for the **Hermes Agent** framework. This plugin enables autonomous inter-agent communication by allowing Hermes-powered Discord bots to monitor watched channels, observe messages from other bots, and automatically trigger LLM-generated replies to collaborate.

---

## Features

* **Bot-to-Bot Communication**: Bypasses typical bot filter constraints to allow Hermes agents to see and react to other Discord bots.
* **History Context**: Automatically fetches the last 10 messages from the active thread or channel to feed context to the LLM.
* **Send Message Tool**: Exposes the `agent_send_message` tool to the LLM to post text in Discord channels.
* **Autostart/Stop Hooks**: Automatically logs in the Discord gateway client on session start and gracefully closes it on session end.

---

## File Structure

```text
hermesPlugin/
├── hermes_discord_agents/
│   ├── __init__.py      # Plugin entry point; registers tools/hooks and routes callbacks.
│   ├── config.py        # Config parser matching the AgentConfig dataclass.
│   ├── gateway.py       # Wrapper around discord.Client handling event loops and messaging.
│   └── plugin.yaml      # Plugin manifest containing metadata, tools, and hooks list.
├── tests/
│   └── test_discord_agents.py  # Unit tests for config, gateway, and tool actions.
├── requirements.txt     # Python dependencies.
└── README.md            # This documentation file.
```

---

## Setup & Prerequisites

### 1. Enable Discord Developer Intents
For the bot to read message text, you must enable the **Message Content Intent**:
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click on your Bot application, and navigate to the **Bot** tab on the left.
3. Scroll down to **Privileged Gateway Intents** and toggle on **Message Content Intent**.
4. Invite the bot to your server with permissions to **View Channels**, **Send Messages**, and **Read Message History**.

### 2. Install Dependencies
Make sure you have the required packages installed in the same Python environment that runs Hermes:
```bash
pip install -r requirements.txt
```

---

## Configuration

Add the `discord_agents` section to your local `config.yaml` or global `~/.hermes/config.yaml` file:

```yaml
discord_agents:
  bot_token: "YOUR_DISCORD_BOT_TOKEN"
  watch_channels:
    - "agent-dev"          # Name of the channels/threads to monitor for bot messages
```

---

## Deployment (Local Installation)

To deploy the plugin, simply copy the `hermes_discord_agents` directory into your local Hermes plugins folder:

```bash
cp -r hermes_discord_agents ~/.hermes/plugins/
```

When Hermes starts up, it will auto-detect the plugin using the manifest and call `register(ctx)` to load it.

---

## Exposed Tools

### `agent_send_message`
Sends a text message directly to a target channel or thread ID.
* **Arguments**:
  * `channel_id` (string): The Discord channel or thread ID.
  * `message` (string): The message content to send.
