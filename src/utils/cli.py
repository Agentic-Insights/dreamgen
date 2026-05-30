"""
Command-line interface for the continuous image generation system.
"""

import asyncio
import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Awaitable, Iterator, Optional, TypeVar

# Fix Windows Unicode handling
if sys.platform == "win32":
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.stderr.encoding != "utf-8":
        sys.stderr.reconfigure(encoding="utf-8")

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from .. import __version__
from ..generators.factory import create_image_generator, is_model_cached, resolve_image_backend
from ..generators.prompt_generator import PromptGenerator
from ..plugins import ensure_initialized, plugin_manager
from ..services import GenerationProgressEvent, GenerationServiceRequest, ImageGenService
from .config import Config
from .logging_config import setup_logging
from .metrics import MetricsCollector
from .troubleshoot import SystemDiagnostics

# Initialize rich console for better output
console = Console()
app = typer.Typer(
    help="DreamGen - Your AI Image Generation Companion",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
plugins_app = typer.Typer(help="Manage prompt entropy plugins")


# Initialize app state
class AppState:
    def __init__(self):
        self.config: Optional[Config] = None


app.state = AppState()
app.add_typer(plugins_app, name="plugins")

HEARTBEAT_SECONDS = 10
T = TypeVar("T")


def get_runtime_config() -> Config:
    """Get the active runtime config, falling back to defaults if needed."""
    if app.state.config is None:
        app.state.config = Config()
    return app.state.config


@contextmanager
def temporary_backend_override(
    config: Config,
    backend_override: Optional[str] = None,
    mock: bool = False,
) -> Iterator[None]:
    """Temporarily apply a one-shot generation backend override."""
    original_backend = config.model.image_backend
    effective_backend = "mock" if mock else backend_override

    try:
        if effective_backend:
            config.model.image_backend = effective_backend.lower()
        yield
    finally:
        config.model.image_backend = original_backend


def create_generator_with_overrides(
    backend_override: Optional[str] = None,
    mock: bool = False,
):
    """Create an image generator while temporarily overriding the configured backend."""
    with temporary_backend_override(app.state.config, backend_override, mock):
        return create_image_generator(app.state.config)


def resolve_backend_with_overrides(
    backend_override: Optional[str] = None,
    mock: bool = False,
) -> str:
    """Resolve the effective backend while honoring one-shot CLI overrides."""
    with temporary_backend_override(app.state.config, backend_override, mock):
        return resolve_image_backend(app.state.config)


def _valid_hf_token() -> bool:
    token = os.getenv("HF_TOKEN", "").strip()
    return bool(token and token != "your_hugging_face_token_here")


def _requires_hf_token(model_name: str) -> bool:
    """Return whether the configured model is commonly gated on Hugging Face."""
    normalized = model_name.lower()
    return any(marker in normalized for marker in ("flux.1-dev", "flux.1-fill"))


def validate_generation_config(config: Config, resolved_backend: str) -> list[str]:
    """Validate config that can fail before submitting long generation work."""
    errors = config.validate()
    valid_backends = {"auto", "flux", "ollama", "zimage", "small", "turbo", "smoke", "mock"}

    if resolved_backend not in valid_backends:
        errors.append(
            f"Invalid image backend: {resolved_backend} "
            "(must be one of auto, flux, ollama, zimage, small, turbo, smoke, mock)"
        )

    if (
        resolved_backend == "flux"
        and _requires_hf_token(config.model.flux_model)
        and not _valid_hf_token()
        and not is_model_cached(config.model.flux_model)
    ):
        errors.append(
            "Flux model "
            f"{config.model.flux_model} appears to require Hugging Face access. "
            "Set HF_TOKEN, pre-cache the model, or choose --backend small, --backend turbo, "
            "or --mock."
        )

    if resolved_backend == "zimage" and not Path(config.model.zimage_model_path).exists():
        errors.append(
            f"Z-Image model path does not exist: {config.model.zimage_model_path}. "
            "Download Tongyi-MAI/Z-Image-Turbo or choose another backend."
        )

    return errors


def _format_model_detail(image_gen: object) -> str:
    model_name = getattr(image_gen, "model_name", None)
    if model_name:
        return str(model_name)

    model_path = getattr(image_gen, "model_path", None)
    if model_path:
        return str(model_path)

    return "unknown"


def _format_device_detail(image_gen: object) -> str:
    return str(getattr(image_gen, "device", "external/default"))


def _requested_backend_name(config: Config, backend_override: Optional[str], mock: bool) -> str:
    if mock:
        return "mock"
    return backend_override or config.model.image_backend


def _format_elapsed(start_time: float) -> str:
    elapsed = int(time.monotonic() - start_time)
    minutes, seconds = divmod(elapsed, 60)
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


async def await_with_generation_status(
    operation: Awaitable[T],
    *,
    backend_name: str,
    phase: str,
    output_path: Path | None,
    heartbeat_seconds: int = HEARTBEAT_SECONDS,
) -> T:
    """Await generation work while a thread emits visible lifecycle status."""
    started_at = time.monotonic()
    stop_event = threading.Event()

    output_detail = f"; output target: {output_path}" if output_path else ""
    console.print(f"[cyan]{phase}:[/cyan] request submitted to {backend_name}{output_detail}")

    def heartbeat() -> None:
        while not stop_event.wait(heartbeat_seconds):
            console.print(
                f"[dim]{phase}: waiting on {backend_name} "
                f"({_format_elapsed(started_at)} elapsed)...[/dim]"
            )

    heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
    heartbeat_thread.start()

    try:
        return await operation
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=1)


def print_generation_service_event(event: GenerationProgressEvent) -> None:
    """Render service lifecycle events that matter to CLI users."""
    if event.name == "prompt_ready":
        console.print(
            Panel(
                f"[bold]Using provided prompt:[/bold]\n\n{event.payload.get('prompt', '')}",
                title="Custom Prompt",
                border_style="blue",
            )
        )
    elif event.name == "prompt_generated":
        console.print(
            Panel(
                f"[bold]Generated prompt:[/bold]\n\n{event.payload.get('prompt', '')}",
                title="AI Prompt",
                border_style="green",
            )
        )
    elif event.name == "output_path_ready":
        output_path = event.payload.get("output_path")
        if output_path:
            console.print(f"[cyan]Saving output to:[/cyan] {output_path}")


@plugins_app.command("list")
def list_plugins() -> None:
    """List registered plugins and their current state."""
    ensure_initialized(get_runtime_config())

    table = Table(title="DreamGen Plugins")
    table.add_column("Name", style="cyan")
    table.add_column("Enabled", style="green")
    table.add_column("Order", justify="right")
    table.add_column("Description")

    for plugin in sorted(plugin_manager.plugins.values(), key=lambda item: (item.order, item.name)):
        table.add_row(
            plugin.name,
            "yes" if plugin.enabled else "no",
            str(plugin.order),
            plugin.description,
        )

    console.print(table)


@plugins_app.command("enable")
def enable_plugin(name: str) -> None:
    """Enable a plugin by name."""
    ensure_initialized(get_runtime_config())

    if name not in plugin_manager.plugins:
        console.print(f"[red]Unknown plugin:[/red] {name}")
        raise typer.Exit(1)

    plugin_manager.enable_plugin(name)
    console.print(f"[green]Enabled plugin:[/green] {name}")


@plugins_app.command("disable")
def disable_plugin(name: str) -> None:
    """Disable a plugin by name."""
    ensure_initialized(get_runtime_config())

    if name not in plugin_manager.plugins:
        console.print(f"[red]Unknown plugin:[/red] {name}")
        raise typer.Exit(1)

    plugin_manager.disable_plugin(name)
    console.print(f"[yellow]Disabled plugin:[/yellow] {name}")


def version_callback(value: bool):
    """Display version information."""
    if value:
        console.print(
            Panel.fit(
                "[bold green]DreamGen[/bold green]\n"
                f"Version: {__version__}\n"
                "Using: Ollama for prompts and configurable local image backends"
            )
        )
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=version_callback,
        help="Show version information and exit",
        is_eager=True,
    ),
    config_file: Optional[Path] = typer.Option(
        None, "--config", "-c", help="Path to configuration file"
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable verbose logging to console",
    ),
):
    """
    🎨 DreamGen

    Generate AI images using Ollama for prompts and local image backends.
    Run `uv run dreamgen generate` for CLI usage, or use Docker Compose for the web UI.
    """
    try:
        if config_file and config_file.exists():
            app.state.config = Config.from_file(config_file)
        else:
            if config_file and not config_file.exists():
                console.print(
                    f"[yellow]Warning: Config file {config_file} not found, using defaults[/yellow]"
                )
            app.state.config = Config()
    except ValueError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(1) from exc

    # Configure logging after configuration is loaded
    setup_logging(app.state.config.system.log_dir, verbose=debug)


@app.command(help="Generate a single image with optional interactive prompt refinement")
def generate(
    interactive: bool = typer.Option(
        False, "--interactive", "-i", help="Enable interactive mode with prompt feedback"
    ),
    prompt: Optional[str] = typer.Option(
        None, "--prompt", "-p", help="Provide a custom prompt for direct inference"
    ),
    backend: Optional[str] = typer.Option(
        None,
        "--backend",
        "--model",
        help="Override the image backend for this run (flux, ollama, zimage, small, turbo, smoke, mock)",
    ),
    mock: bool = typer.Option(
        False,
        "--mock",
        help="Use mock image generator (no GPU required, generates placeholder images)",
    ),
    mps_use_fp16: bool = typer.Option(
        False,
        "--mps-use-fp16",
        help="Use float16 precision on Apple Silicon (may improve performance)",
    ),
    summary_json: bool = typer.Option(
        False,
        "--summary-json",
        help="Print a machine-readable generation summary after success",
    ),
) -> None:
    """Generate a single image using AI-generated prompts or a custom prompt."""

    async def _generate() -> None:
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
                console=console,
                transient=True,  # Hide finished tasks
            ) as progress:
                try:
                    # Update config with CLI options
                    app.state.config.system.mps_use_fp16 = mps_use_fp16

                    resolved_backend = resolve_backend_with_overrides(
                        backend_override=backend, mock=mock
                    )
                    validation_errors = validate_generation_config(
                        app.state.config, resolved_backend
                    )
                    if validation_errors:
                        for error in validation_errors:
                            console.print(f"[red]Configuration error:[/red] {error}")
                        raise typer.Exit(1)

                    # Initialize components
                    init_task = progress.add_task(
                        "[cyan]Initializing generation service...", total=None
                    )
                    if mock:
                        console.print(
                            "[yellow]Using mock image generator (no GPU required)[/yellow]"
                        )
                    service = ImageGenService(
                        app.state.config, output_dir=app.state.config.system.output_dir
                    )
                    metrics = MetricsCollector(app.state.config.system.log_dir / "metrics")
                    progress.remove_task(init_task)

                    console.print(
                        f"[cyan]Using image backend:[/cyan] {resolved_backend} "
                        f"(resolved: {resolved_backend}, "
                        f"requested: {_requested_backend_name(app.state.config, backend, mock)})"
                    )

                    # Start metrics collection
                    metrics.start_batch()

                    generation_prompt = prompt
                    if not prompt and interactive:
                        prompt_gen = PromptGenerator(app.state.config)
                        prompt_task = progress.add_task(
                            "[cyan]Generating creative prompt...", total=None
                        )
                        try:
                            generation_prompt = await prompt_gen.get_prompt_with_feedback()
                        finally:
                            progress.remove_task(prompt_task)
                            prompt_gen.cleanup()

                    # Generate image
                    image_task = progress.add_task("[cyan]Generating image...", total=None)
                    try:
                        with temporary_backend_override(app.state.config, backend, mock):
                            result = await await_with_generation_status(
                                service.generate(
                                    GenerationServiceRequest(
                                        prompt=generation_prompt,
                                        cleanup=True,
                                    ),
                                    callback=print_generation_service_event,
                                ),
                                backend_name=resolved_backend,
                                phase="Image generation",
                                output_path=None,
                            )
                    except Exception as e:
                        console.print(
                            f"[red]Generation failed[/red]\n"
                            f"Backend: {resolved_backend}\n"
                            "Phase: image generation\n"
                            f"Error: {str(e)}"
                        )
                        raise typer.Exit(1) from e
                    finally:
                        progress.remove_task(image_task)

                    console.print(
                        f"[cyan]Model/provider:[/cyan] {result.model_name}; "
                        f"backend: {result.backend}"
                    )
                    console.print(
                        f"[green]Image received and saved[/green] ({result.generation_time:.1f}s)"
                    )

                    # Show success message with details
                    console.print(
                        Panel(
                            f"[bold green]Image generated successfully![/bold green]\n\n"
                            f"Saved to: {result.image_path}\n"
                            f"Prompt saved to: {result.image_path.with_suffix('.txt')}\n\n"
                            f"[dim]Model: {result.model_name}\n"
                            f"Backend: {result.backend}\n"
                            f"Time: {result.generation_time:.1f}s\n"
                            f"Prompt: {result.prompt}[/dim]",
                            title="Success",
                            border_style="green",
                        )
                    )
                    if summary_json:
                        print(
                            json.dumps(
                                {
                                    "image_path": str(result.image_path),
                                    "prompt_path": str(result.image_path.with_suffix(".txt")),
                                    "relative_image_path": result.relative_image_path,
                                    "prompt": result.prompt,
                                    "backend": result.backend,
                                    "model": result.model_name,
                                    "generation_time": result.generation_time,
                                    "metadata": result.metadata,
                                    "created_at": result.created_at,
                                },
                                sort_keys=True,
                            )
                        )

                    # End metrics collection
                    metrics.end_batch()

                except typer.Exit:
                    raise
                except Exception as e:
                    console.print(f"[red]Error: {str(e)}[/red]")
                    raise
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]Error: {str(e)}[/red]")
            raise typer.Exit(1)

    try:
        asyncio.run(_generate())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user")


@app.command(help="Run system diagnostics and troubleshooting")
def diagnose(
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Show detailed diagnostic information"
    ),
    check_env: bool = typer.Option(
        True, "--check-env/--no-check-env", help="Check environment variables"
    ),
    fix: bool = typer.Option(False, "--fix", help="Attempt to fix common issues automatically"),
) -> None:
    """Run diagnostics to troubleshoot system compatibility and configuration issues."""
    console = Console()

    try:
        # Initialize diagnostics with config if available
        diagnostics = SystemDiagnostics(app.state.config)

        # Run and print diagnostics
        diagnostics.print_diagnostics(verbose=verbose, check_env=check_env)

        # If fix flag is set, attempt to fix common issues
        if fix:
            console.print("\n[bold cyan]Attempting to fix common issues...[/bold cyan]")
            diag_results = diagnostics.run_diagnostics()
            fixed = diagnostics.fix_common_issues(diag_results)

            if fixed:
                console.print("\n[bold green]Fixed Issues:[/bold green]")
                for i, fix_msg in enumerate(fixed, 1):
                    console.print(f"{i}. {fix_msg}")
            else:
                console.print("\n[yellow]No automatic fixes were applied.[/yellow]")

            # Suggest manual fixes
            suggested_fixes = diagnostics.suggest_fixes(diag_results)
            if suggested_fixes:
                console.print("\n[bold yellow]Suggested Manual Fixes:[/bold yellow]")
                for i, fix_msg in enumerate(suggested_fixes, 1):
                    console.print(f"{i}. {fix_msg}")

    except Exception as e:
        console.print(f"[red]Error running diagnostics: {str(e)}[/red]")
        raise typer.Exit(1)


@app.command(help="Publish approved gallery assets to Cloudflare R2")
def publish(
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        help="Generated output directory containing the publication catalog",
    ),
    bucket: str = typer.Option("dreamgen-gallery", "--bucket", help="Target R2 bucket"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Maximum approved images to upload"),
    since: Optional[str] = typer.Option(
        None,
        "--since",
        help="Only include images modified on or after YYYY-MM-DD",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview the publish plan without uploading. This is the default.",
    ),
    execute: bool = typer.Option(False, "--execute", help="Upload the planned files"),
    include_featured: bool = typer.Option(
        True,
        "--include-featured/--exclude-featured",
        help="Include featured assets along with published assets",
    ),
    prune: bool = typer.Option(
        False,
        "--prune",
        help="Reserve remote deletion intent. Current publisher still reports delete_objects=0.",
    ),
    smoke_test: bool = typer.Option(
        False,
        "--smoke-test",
        help="Validate R2 write/delete access before publishing",
    ),
    smoke_test_only: bool = typer.Option(
        False,
        "--smoke-test-only",
        help="Only run the R2 smoke test; do not publish gallery assets afterward",
    ),
    local: bool = typer.Option(
        False,
        "--local",
        help="Use Wrangler's local R2 simulation instead of remote Cloudflare R2",
    ),
    wrangler_package: str = typer.Option(
        "wrangler@4",
        "--wrangler-package",
        help="Package passed to npx, for example wrangler@4",
    ),
) -> None:
    """Publish only catalog-approved gallery assets."""
    if dry_run and execute:
        console.print("[red]Choose either --dry-run or --execute, not both.[/red]")
        raise typer.Exit(1)

    from .gallery_publisher import publish_gallery

    try:
        publish_gallery(
            output_dir=output_dir or app.state.config.system.output_dir,
            bucket=bucket,
            since=since,
            limit=limit,
            execute=execute,
            include_featured=include_featured,
            prune=prune,
            smoke=smoke_test,
            smoke_only=smoke_test_only,
            local=local,
            wrangler_package=wrangler_package,
        )
    except SystemExit as exc:
        console.print(f"[red]{exc.code}[/red]")
        raise typer.Exit(1) from exc


@app.command(help="Generate multiple images in a batch with configurable settings")
def loop(
    batch_size: int = typer.Option(
        5, "--batch-size", "-b", help="Number of images to generate per run", min=1, max=100
    ),
    interval: Optional[int] = typer.Option(
        None, "--interval", "-n", help="Interval in seconds between generations", min=0
    ),
    backend: Optional[str] = typer.Option(
        None,
        "--backend",
        "--model",
        help="Override the image backend for this run (flux, ollama, zimage, small, turbo, smoke, mock)",
    ),
    mock: bool = typer.Option(
        False,
        "--mock",
        help="Use mock image generator (no GPU required, generates placeholder images)",
    ),
    mps_use_fp16: bool = typer.Option(
        False,
        "--mps-use-fp16",
        help="Use float16 precision on Apple Silicon (may improve performance)",
    ),
) -> None:
    """Generate a batch of images with unique prompts."""

    async def _loop() -> None:
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=console,
                transient=True,  # Hide finished tasks
            ) as progress:
                try:
                    # Update config with CLI options
                    app.state.config.system.mps_use_fp16 = mps_use_fp16

                    resolved_backend = resolve_backend_with_overrides(
                        backend_override=backend, mock=mock
                    )
                    validation_errors = validate_generation_config(
                        app.state.config, resolved_backend
                    )
                    if validation_errors:
                        for error in validation_errors:
                            console.print(f"[red]Configuration error:[/red] {error}")
                        raise typer.Exit(1)

                    # Initialize components
                    init_task = progress.add_task("[cyan]Initializing models...", total=None)
                    prompt_gen = PromptGenerator(app.state.config)
                    if mock:
                        console.print(
                            "[yellow]Using mock image generator (no GPU required)[/yellow]"
                        )
                        image_gen, backend_name = create_generator_with_overrides(mock=True)
                    else:
                        image_gen, backend_name = create_generator_with_overrides(
                            backend_override=backend
                        )
                    service = ImageGenService(
                        app.state.config, output_dir=app.state.config.system.output_dir
                    )
                    metrics = MetricsCollector(app.state.config.system.log_dir / "metrics")
                    progress.remove_task(init_task)

                    console.print(
                        f"[cyan]Using image backend:[/cyan] {backend_name} "
                        f"(resolved: {resolved_backend}, "
                        f"requested: {_requested_backend_name(app.state.config, backend, mock)})"
                    )
                    console.print(
                        f"[cyan]Model/provider:[/cyan] {_format_model_detail(image_gen)}; "
                        f"device: {_format_device_detail(image_gen)}"
                    )

                    # Start metrics collection
                    metrics.start_batch()

                    console.print(
                        f"\n[bold]Starting batch generation of {batch_size} images...[/bold]"
                    )

                    batch_task = progress.add_task("[cyan]Generating images", total=batch_size)

                    for i in range(batch_size):
                        try:
                            # Generate prompt
                            prompt = await prompt_gen.generate_prompt()
                            console.print(
                                Panel(
                                    f"[bold]Generated prompt for image {i+1}:[/bold]\n\n{prompt}",
                                    title=f"Prompt {i+1}/{batch_size}",
                                    border_style="blue",
                                )
                            )

                            def print_loop_event(event: GenerationProgressEvent) -> None:
                                if event.name == "output_path_ready":
                                    output_path = event.payload.get("output_path")
                                    if output_path:
                                        console.print(
                                            f"[cyan]Image {i+1}/{batch_size} output target:[/cyan] "
                                            f"{output_path}"
                                        )

                            force_reinit = i > 0 and i % 5 == 0  # Reinit every 5 images
                            with temporary_backend_override(app.state.config, backend, mock):
                                result = await await_with_generation_status(
                                    service.generate(
                                        GenerationServiceRequest(
                                            prompt=prompt,
                                            force_reinit=force_reinit,
                                        ),
                                        callback=print_loop_event,
                                        backend=image_gen,
                                        backend_name=backend_name,
                                    ),
                                    backend_name=backend_name,
                                    phase=f"Image {i+1}/{batch_size} generation",
                                    output_path=None,
                                )
                            model_name = result.model_name

                            console.print(
                                f"[green]✓[/green] Image {i+1} generated in "
                                f"{result.generation_time:.1f}s using {result.model_name}\n"
                                f"   {result.image_path}"
                            )

                            progress.update(batch_task, advance=1)

                            # Always wait at least 1 second between generations
                            wait_time = max(1, interval or 0)
                            if i < batch_size - 1:
                                await asyncio.sleep(wait_time)

                        except Exception as e:
                            console.print(
                                f"[red]Generation failed[/red]\n"
                                f"Backend: {backend_name}\n"
                                f"Phase: image {i+1}/{batch_size} generation\n"
                                f"Error: {str(e)}"
                            )
                            if i < batch_size - 1:
                                console.print("[yellow]Attempting recovery...[/yellow]")
                                await asyncio.sleep(2)  # Wait for cleanup
                                console.print("[yellow]Continuing with next image...[/yellow]")
                                continue
                            raise typer.Exit(1) from e

                    # End metrics collection and show summary
                    metrics.end_batch()
                    perf_metrics = metrics.get_performance_metrics()

                    console.print(
                        Panel(
                            f"[bold green]Batch generation complete![/bold green]\n"
                            f"Successfully created {batch_size} images using {model_name}\n\n"
                            f"[dim]Performance Metrics:\n"
                            f"Average Generation Time: {perf_metrics.get('avg_generation_time', 0):.1f}s\n"
                            f"Average GPU Memory: {perf_metrics.get('avg_gpu_memory', 0):.1f} GB\n"
                            f"Success Rate: {perf_metrics.get('success_rate', 0)*100:.1f}%[/dim]",
                            title="Success",
                            border_style="green",
                        )
                    )

                    # Final cleanup
                    prompt_gen.cleanup()
                    image_gen.cleanup()

                except typer.Exit:
                    raise
                except Exception as e:
                    console.print(f"[red]Error: {str(e)}[/red]")
                    raise
        except typer.Exit:
            raise
        except Exception as e:
            console.print(f"[red]Error: {str(e)}[/red]")
            raise typer.Exit(1)

    try:
        asyncio.run(_loop())
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/yellow]")
        raise typer.Exit(0)
    except typer.Exit:
        raise
    except Exception as e:
        Console(stderr=True).print(f"[red]Error: {str(e)}[/red]")
        raise typer.Exit(1)
