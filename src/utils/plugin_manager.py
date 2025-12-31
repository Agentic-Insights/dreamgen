"""
Plugin management system for controlling and logging plugin execution.
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List


@dataclass
class PluginInfo:
    """Information about a registered plugin."""

    name: str
    description: str
    function: Callable
    enabled: bool = True
    order: int = 999  # Default to end of list


@dataclass
class PluginResult:
    """Result of a plugin execution including its contribution."""

    name: str
    value: Any
    description: str


class PluginManager:
    def __init__(self):
        self.plugins: Dict[str, PluginInfo] = {}
        self.logger = logging.getLogger(__name__)

    def register(
        self,
        name: str,
        description: str,
        function: Callable,
        enabled: bool = True,
        order: int = 999,
    ):
        """Register a new plugin with the system."""
        self.plugins[name] = PluginInfo(
            name=name, description=description, function=function, enabled=enabled, order=order
        )
        self.logger.debug(
            "Registered plugin: %s (enabled=%s, order=%s)",
            name,
            enabled,
            order,
        )

    def enable_plugin(self, name: str):
        """Enable a specific plugin."""
        if name in self.plugins:
            self.plugins[name].enabled = True
            self.logger.debug("Enabled plugin: %s", name)

    def disable_plugin(self, name: str):
        """Disable a specific plugin."""
        if name in self.plugins:
            self.plugins[name].enabled = False
            self.logger.debug("Disabled plugin: %s", name)

    def is_enabled(self, name: str) -> bool:
        """Check if a plugin is enabled."""
        if name in self.plugins:
            return self.plugins[name].enabled
        return False

    def set_plugin_order(self, name: str, order: int):
        """Set the execution order for a plugin."""
        if name in self.plugins:
            self.plugins[name].order = order
            self.logger.debug("Set order for plugin %s: %s", name, order)

    def execute_plugins(self) -> List[PluginResult]:
        """
        Execute all enabled plugins in their specified order.
        Returns a list of plugin results with their contributions.
        """
        results = []

        # Sort plugins by order
        sorted_plugins = sorted(
            [p for p in self.plugins.values() if p.enabled], key=lambda x: x.order
        )

        for plugin in sorted_plugins:
            try:
                self.logger.debug(f"Executing plugin: {plugin.name}")
                value = plugin.function()
                if value is not None:
                    result = PluginResult(
                        name=plugin.name, value=value, description=plugin.description
                    )
                    results.append(result)
                    self.logger.info(
                        f"Plugin {plugin.name} contribution: {value} " f"({plugin.description})"
                    )
            except Exception as e:
                self.logger.error(f"Error executing plugin {plugin.name}: {str(e)}")

        return results

    def get_plugin_descriptions(self) -> List[str]:
        """Get descriptions of all enabled plugins."""
        return [f"{p.name}: {p.description}" for p in self.plugins.values() if p.enabled]
