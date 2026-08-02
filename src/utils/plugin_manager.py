"""
Plugin management system for controlling and logging plugin execution.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

PLUGIN_CATEGORIES = frozenset({"entropy", "context", "style", "operational"})


def normalize_plugin_category(category: str) -> str:
    """Keep category metadata bounded while preserving legacy registrations."""
    normalized = str(category).strip().lower()
    return normalized if normalized in PLUGIN_CATEGORIES else "context"


@dataclass
class PluginInfo:
    """Information about a registered plugin."""

    name: str
    description: str
    function: Callable
    enabled: bool = True
    order: int = 999  # Default to end of list
    category: str = "context"
    kind: str = "prompt"
    phase: str = "prompt"


@dataclass
class PluginResult:
    """Result of a plugin execution including its contribution."""

    name: str
    value: Any
    description: str
    category: str = "context"
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GuardInfo:
    """Operational hook metadata kept separate from prompt plugins."""

    name: str
    description: str
    pre_hook: Callable[[Dict[str, Any]], Dict[str, Any] | None] | None = None
    post_hook: Callable[[Dict[str, Any]], Dict[str, Any] | None] | None = None
    enabled: bool = True
    category: str = "operational"
    phase: str = "pre+post"


class PluginManager:
    def __init__(self):
        self.plugins: Dict[str, PluginInfo] = {}
        self.guards: Dict[str, GuardInfo] = {}
        self.logger = logging.getLogger(__name__)

    def register(
        self,
        name: str,
        description: str,
        function: Callable,
        enabled: bool = True,
        order: int = 999,
        category: str = "context",
    ):
        """Register a new plugin with the system."""
        self.plugins[name] = PluginInfo(
            name=name,
            description=description,
            function=function,
            enabled=enabled,
            order=order,
            category=normalize_plugin_category(category),
        )
        self.logger.debug(
            "Registered plugin: %s (enabled=%s, order=%s)",
            name,
            enabled,
            order,
        )

    def register_guard(
        self,
        name: str,
        description: str,
        *,
        pre_hook: Callable[[Dict[str, Any]], Dict[str, Any] | None] | None = None,
        post_hook: Callable[[Dict[str, Any]], Dict[str, Any] | None] | None = None,
        enabled: bool = True,
    ) -> None:
        """Register an operational hook without making it a prompt modifier."""
        self.guards[name] = GuardInfo(
            name=name,
            description=description,
            pre_hook=pre_hook,
            post_hook=post_hook,
            enabled=enabled,
        )
        self.logger.debug("Registered guard: %s (enabled=%s)", name, enabled)

    def enable_plugin(self, name: str):
        """Enable a specific plugin."""
        if name in self.plugins:
            self.plugins[name].enabled = True
            self.logger.debug("Enabled plugin: %s", name)
        elif name in self.guards:
            self.guards[name].enabled = True
            self.logger.debug("Enabled guard: %s", name)

    def disable_plugin(self, name: str):
        """Disable a specific plugin."""
        if name in self.plugins:
            self.plugins[name].enabled = False
            self.logger.debug("Disabled plugin: %s", name)
        elif name in self.guards:
            self.guards[name].enabled = False
            self.logger.debug("Disabled guard: %s", name)

    def is_enabled(self, name: str) -> bool:
        """Check if a plugin is enabled."""
        if name in self.plugins:
            return self.plugins[name].enabled
        if name in self.guards:
            return self.guards[name].enabled
        return False

    def set_plugin_order(self, name: str, order: int):
        """Set the execution order for a plugin."""
        if name in self.plugins:
            self.plugins[name].order = order
            self.logger.debug("Set order for plugin %s: %s", name, order)

    def execute_plugins(
        self,
        overrides: Dict[str, Any] | None = None,
        override_provenance: Dict[str, Dict[str, Any]] | None = None,
    ) -> List[PluginResult]:
        """
        Execute all enabled plugins in their specified order.
        Values supplied in ``overrides`` are used without calling that plugin.
        This lets a generation plan resolve a random choice once and replay it
        through prompt and renderer consumers without another random draw.
        Returns a list of plugin results with their contributions.
        """
        results = []
        resolved_overrides = overrides or {}
        resolved_provenance = override_provenance or {}

        # Sort plugins by order
        sorted_plugins = sorted(
            [p for p in self.plugins.values() if p.enabled], key=lambda x: x.order
        )

        for plugin in sorted_plugins:
            try:
                self.logger.debug(f"Executing plugin: {plugin.name}")
                value = (
                    resolved_overrides[plugin.name]
                    if plugin.name in resolved_overrides
                    else plugin.function()
                )
                if value is not None:
                    result = PluginResult(
                        name=plugin.name,
                        value=value,
                        description=plugin.description,
                        category=plugin.category,
                        provenance=dict(resolved_provenance.get(plugin.name, {})),
                    )
                    results.append(result)
                    self.logger.info(
                        f"Plugin {plugin.name} contribution: {value} " f"({plugin.description})"
                    )
            except Exception as e:
                self.logger.error(f"Error executing plugin {plugin.name}: {str(e)}")

        return results

    def execute_guards(self, phase: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Run operational hooks and return structured, sidecar-safe results."""
        results: List[Dict[str, Any]] = []
        for guard in self.guards.values():
            if not guard.enabled:
                continue
            hook = (
                guard.pre_hook if phase == "pre" else guard.post_hook if phase == "post" else None
            )
            if hook is None:
                continue
            try:
                details = hook(context) or {}
                status = str(details.pop("status", "passed"))
                results.append(
                    {
                        "name": guard.name,
                        "category": guard.category,
                        "phase": phase,
                        "status": status,
                        "details": details,
                    }
                )
            except Exception as exc:  # pragma: no cover - defensive guard boundary
                self.logger.error("Guard %s failed during %s phase: %s", guard.name, phase, exc)
                results.append(
                    {
                        "name": guard.name,
                        "category": guard.category,
                        "phase": phase,
                        "status": "failed",
                        "details": {"error": str(exc)},
                    }
                )
        return results

    def registry_entries(self) -> List[PluginInfo]:
        """Return prompt plugins and operational guards for API/UI discovery."""
        entries = list(self.plugins.values())
        entries.extend(
            PluginInfo(
                name=guard.name,
                description=guard.description,
                function=lambda: None,
                enabled=guard.enabled,
                order=999,
                category=guard.category,
                kind="guard",
                phase=guard.phase,
            )
            for guard in self.guards.values()
        )
        return sorted(entries, key=lambda info: (info.order, info.name))

    def get_plugin_descriptions(self) -> List[str]:
        """Get descriptions of all enabled plugins."""
        return [f"{p.name}: {p.description}" for p in self.plugins.values() if p.enabled]
