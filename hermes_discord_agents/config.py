import logging
import yaml
from pathlib import Path
from dataclasses import dataclass, field

# Set up logging for configuration loading
logger = logging.getLogger("hermes.discord_config")

@dataclass
class AgentConfig:
    """Dataclass holding all plugin configurations."""
    bot_token: str = ""                                # Discord bot authentication token
    watch_channels: list[str] = field(default_factory=list) # List of Discord channel names to monitor

def load_config(config_path: Path = None) -> AgentConfig:
    """Load config from a yaml file. 
    Checks the local workspace directory first, then fallback to ~/.hermes/config.yaml.
    
    Args:
        config_path (Path, optional): Explicit path to config file.
        
    Returns:
        AgentConfig: Loaded configuration object.
    """
    # Step 1: Resolve config path automatically if not provided
    if config_path is None:
        # Check current working directory first
        local_cfg = Path("config.yaml")
        if local_cfg.exists():
            config_path = local_cfg
        else:
            # Fall back to user's home folder under .hermes directory
            home_cfg = Path.home() / ".hermes" / "config.yaml"
            if home_cfg.exists():
                config_path = home_cfg

    cfg = AgentConfig()
    # Step 2: Return default empty config if no file is found
    if not config_path or not config_path.exists():
        return cfg

    # Step 3: Open and parse the YAML file
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            
        # Step 4: Extract discord_agents section (fall back to root dict if absent)
        discord_data = data.get("discord_agents", {})
        if not discord_data:
            discord_data = data

        # Step 5: Map properties to target config object
        if "bot_token" in discord_data:
            cfg.bot_token = str(discord_data["bot_token"])
            
        if "watch_channels" in discord_data:
            # Validate that watch_channels is a list structure
            if isinstance(discord_data["watch_channels"], list):
                cfg.watch_channels = [str(x) for x in discord_data["watch_channels"]]
            else:
                raise ValueError("Config field 'watch_channels' must be a list of strings")
    except Exception as e:
        logger.error("Failed to parse configuration at %s: %s", config_path, e)
        raise ValueError(f"Failed to parse configuration at {config_path}: {e}") from e

    return cfg
