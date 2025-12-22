"""
Plugin system for adding contextual information to prompts.
"""

import logging
from typing import Any, Dict, List

from ..utils.config import Config
from ..utils.plugin_manager import PluginManager, PluginResult
from .art_style import get_art_style
from .holiday_fact import get_holiday_fact
from .lora import apply_lora
from .nearest_holiday import get_nearest_holiday
from .time_of_day import get_time_of_day

# Initialize plugin manager
plugin_manager = PluginManager()

# Initialize plugins dict to store plugin functions
plugin_functions = {}


def register_base_plugins():
    """Register the base plugins that don't require additional configuration."""
    plugin_manager.register(
        "time_of_day",
        "Provides temporal context based on the current time of day",
        get_time_of_day,
        order=1,
    )

    plugin_manager.register(
        "nearest_holiday",
        "Adds context about upcoming or current holidays",
        get_nearest_holiday,
        order=2,
    )

    plugin_manager.register(
        "holiday_fact", "Enriches holiday context with interesting facts", get_holiday_fact, order=3
    )

    plugin_manager.register(
        "art_style", "Suggests an artistic style for the image", get_art_style, order=4
    )


def register_lora_plugin(config: Config):
    """Register the Lora plugin with the given config."""

    def lora_plugin():
        return apply_lora(config)

    # Store the plugin function
    plugin_functions["lora"] = lora_plugin

    # Register or re-register the plugin
    plugin_manager.register(
        "lora", "Randomly selects and applies a Lora model", lora_plugin, order=5
    )


# Register base plugins immediately
register_base_plugins()

logger = logging.getLogger(__name__)

# Track initialization state
_initialized = False


def initialize_plugins(config: Config) -> None:
    """Initialize all plugins with the given config."""
    global _initialized
    register_lora_plugin(config)

    # Enable plugins based on config
    for name in config.plugins.enabled_plugins:
        if name in plugin_manager.plugins:
            plugin_manager.enable_plugin(name)

    _initialized = True


def ensure_initialized(config: Config) -> None:
    """Ensure plugins are initialized, initializing if needed."""
    global _initialized
    if not _initialized:
        initialize_plugins(config)


def get_context_with_descriptions() -> Dict[str, Any]:
    """
    Execute plugins and return their results with descriptions.

    Returns:
        Dict containing plugin results and their descriptions
    """
    results = plugin_manager.execute_plugins()

    # Log the contributions of each plugin
    for result in results:
        logger.info(f"Plugin contribution - {result.name}: {result.value} ({result.description})")

    return {"results": results, "descriptions": plugin_manager.get_plugin_descriptions()}


def get_temporal_descriptor() -> str:
    """
    Creates a human-readable string combining all plugin contributions.

    Returns:
        str: A descriptive string combining all enabled plugin outputs
    """
    results = plugin_manager.execute_plugins()

    # Build the descriptor string
    parts = []
    holiday_fact = None
    art_style = None

    for result in results:
        if result.name == "holiday_fact":
            holiday_fact = result.value
        elif result.name == "art_style":
            art_style = result.value
        else:
            if result.value:
                parts.append(str(result.value))

    # Join the main parts
    descriptor = ", ".join(filter(None, parts))

    # Add holiday fact if available
    if holiday_fact:
        descriptor = f"{descriptor} ({holiday_fact})"

    # Add art style if available
    if art_style:
        descriptor = f"{descriptor}, {art_style}"

    logger.info(f"Generated temporal descriptor: {descriptor}")
    return descriptor
