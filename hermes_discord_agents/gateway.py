import asyncio
import logging
from typing import Callable, Optional

# Set up logging for the Discord gateway component
logger = logging.getLogger("hermes.discord_gateway")

class DiscordGateway:
    """A wrapper class around the discord.py Client to manage connection states,
    incoming events, and outgoing messages.
    """
    def __init__(self, config, on_message_callback: Callable):
        self.config = config                          # AgentConfig object
        self.on_message_callback = on_message_callback  # Callback function for incoming bot messages
        self.client = None                            # The discord.Client instance
        self.task = None                              # Background asyncio Task running the client loop
        self.ready_event = None                       # Event to signal when the client has successfully authenticated

    async def start(self) -> bool:
        """Starts the Discord gateway client in a background task.
        
        Returns:
            bool: True if connection/ready event succeeded within timeout, False otherwise.
        """
        # Step 1: Validate configured Discord token
        if not self.config.bot_token or self.config.bot_token == "YOUR_BOT_TOKEN_HERE":
            logger.warning("No valid Discord bot token configured. Gateway disabled.")
            return False

        # Step 2: Try lazy importing discord.py
        try:
            import discord
        except ImportError:
            logger.error("discord.py is not installed. Run `pip install -r requirements.txt`.")
            return False

        # Step 3: Configure privileged message content intents
        intents = discord.Intents.default()
        intents.message_content = True  # Required to read text content of messages

        # Step 4: Instantiate the Discord client and the connection event
        self.client = discord.Client(intents=intents)
        self.ready_event = asyncio.Event()

        # Step 5: Define event listener for successful login
        @self.client.event
        async def on_ready():
            logger.info("Discord Gateway logged in as %s (ID: %s)", self.client.user, self.client.user.id)
            self.ready_event.set()  # Signal that connection is ready

        # Step 6: Define event listener for incoming messages
        @self.client.event
        async def on_message(message):
            # Do not process messages sent by this bot itself
            if self.client and message.author.id == self.client.user.id:
                return

            # Check if the message was posted in a watched channel or thread
            is_watched = False
            channel_name = getattr(message.channel, "name", "")

            # If the channel is a thread, check if the parent channel is watched
            if isinstance(message.channel, discord.Thread):
                parent = message.channel.parent
                if parent is None and getattr(message.channel, "parent_id", None):
                    try:
                        # Attempt to resolve the parent channel from cache or fetch from guild
                        parent = message.guild.get_channel(message.channel.parent_id)
                        if not parent:
                            parent = await message.guild.fetch_channel(message.channel.parent_id)
                    except Exception:
                        pass

                if parent:
                    parent_name = getattr(parent, "name", "")
                    if parent_name in self.config.watch_channels:
                        is_watched = True
            # For standard text channels, directly check if the channel name is watched
            elif channel_name in self.config.watch_channels:
                is_watched = True

            # Step 7: Forward the message to the plugin handler callback if watched
            if is_watched:
                await self.on_message_callback(message)

        # Step 8: Start the client event loop inside a background task
        logger.info("Starting Discord client task in background...")
        self.task = asyncio.create_task(self.client.start(self.config.bot_token))

        # Step 9: Block asynchronously until client signals ready state or times out (10s limit)
        try:
            await asyncio.wait_for(self.ready_event.wait(), timeout=10.0)
            return True
        except (asyncio.TimeoutError, Exception) as e:
            logger.error("Failed to start Discord client: %s", e)
            await self.stop()
            return False

    async def stop(self):
        """Disconnect and stop client, cleaning up background tasks."""
        # Step 1: Disconnect the Discord client safely
        if self.client and not self.client.is_closed():
            logger.info("Disconnecting Discord Gateway...")
            await self.client.close()
        # Step 2: Cancel the background event loop task
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def send_message(self, channel_id: int, content: str) -> Optional[str]:
        """Send a message to a Discord channel/thread, truncating to 2000 characters if necessary.
        
        Args:
            channel_id (int): The target channel or thread ID.
            content (str): The text content to post.
            
        Returns:
            Optional[str]: The message ID string if successful, None otherwise.
        """
        if not self.client:
            logger.error("Cannot send message: Discord Gateway not active.")
            return None
        try:
            # Step 1: Get channel object from local cache, or fetch it from API
            channel = self.client.get_channel(channel_id)
            if not channel:
                channel = await self.client.fetch_channel(channel_id)
            
            # Step 2: Send the message (enforcing Discord's 2000 character limit)
            if channel:
                msg = await channel.send(content[:2000])
                return str(msg.id)
        except Exception as e:
            logger.error("Failed to send message: %s", e)
        return None
