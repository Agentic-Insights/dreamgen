"""Tests for plugin CLI commands."""

from typer.testing import CliRunner

from src.plugins import initialize_plugins, plugin_manager
from src.utils.cli import app
from src.utils.config import Config

runner = CliRunner()


def setup_function(function):
    """Reset plugin state before each test."""
    initialize_plugins(Config())


def test_plugin_list_displays_plugins():
    """Test that plugin list command shows available plugins."""
    result = runner.invoke(app, ["plugins", "list"])
    assert result.exit_code == 0
    assert "time_of_day" in result.stdout


def test_enable_disable_plugin_changes_state():
    """Test that enable/disable commands modify plugin state."""
    runner.invoke(app, ["plugins", "disable", "time_of_day"])
    assert not plugin_manager.plugins["time_of_day"].enabled

    runner.invoke(app, ["plugins", "enable", "time_of_day"])
    assert plugin_manager.plugins["time_of_day"].enabled
