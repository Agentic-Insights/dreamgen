"""
Troubleshooting utilities for diagnosing system compatibility and configuration issues.
"""

import os
import platform
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Literal, Optional, Tuple

import psutil
import torch
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from .config import Config


class SystemDiagnostics:
    def __init__(self, config: Optional[Config] = None):
        """Initialize the diagnostics system with optional configuration."""
        self.config = config
        self.console = Console()

    def check_python_environment(self) -> Dict[str, Any]:
        """Check Python version and environment details."""
        result = {
            "python_version": sys.version,
            "python_path": sys.executable,
            "platform": platform.platform(),
            "processor": platform.processor(),
            "architecture": platform.architecture()[0],
            "virtual_env": os.environ.get("VIRTUAL_ENV"),
            "issues": [],
        }

        # Check Python version
        major, minor, _ = sys.version_info[:3]
        if major < 3 or (major == 3 and minor < 8):
            result["issues"].append(f"Python version {major}.{minor} is below recommended 3.8+")

        return result

    def check_torch_installation(self) -> Dict[str, Any]:
        """Check PyTorch installation details."""
        result = {
            "torch_version": torch.__version__,
            "torch_path": torch.__file__,
            "torch_config": None,
            "issues": [],
        }

        # Get PyTorch build configuration
        try:
            result["torch_config"] = torch.__config__.show()
        except Exception:
            result["torch_config"] = "Unable to retrieve build configuration"
            result["issues"].append("Failed to retrieve PyTorch build configuration")

        # Check for minimum version
        version_parts = torch.__version__.split(".")
        if len(version_parts) >= 2:
            major, minor = map(int, version_parts[:2])
            if major < 1 or (major == 1 and minor < 10):
                result["issues"].append(
                    f"PyTorch version {torch.__version__} is below recommended 1.10+"
                )

        return result

    def check_gpu_support(self) -> Dict[str, Any]:
        """Check for GPU support (CUDA or MPS)."""
        result = {
            "cuda_available": torch.cuda.is_available(),
            "cuda_version": torch.version.cuda if hasattr(torch.version, "cuda") else None,
            "cuda_devices": [],
            "mps_available": hasattr(torch.backends, "mps") and torch.backends.mps.is_available(),
            "mps_built": hasattr(torch.backends, "mps") and torch.backends.mps.is_built(),
            "device_type": "cpu",  # Default
            "issues": [],
        }

        # Check CUDA devices
        if result["cuda_available"]:
            result["device_type"] = "cuda"
            for i in range(torch.cuda.device_count()):
                result["cuda_devices"].append(
                    {
                        "index": i,
                        "name": torch.cuda.get_device_name(i),
                        "memory": torch.cuda.get_device_properties(i).total_memory
                        / (1024**3),  # GB
                    }
                )

        # Check MPS (Apple Silicon)
        if result["mps_available"]:
            result["device_type"] = "mps"

        # Check for issues
        if not result["cuda_available"] and not result["mps_available"]:
            result["issues"].append("No GPU acceleration available (CPU only)")

            # Check if MPS is built but not available
            if result["mps_built"] and not result["mps_available"]:
                result["issues"].append(
                    "MPS is built but not available. This might be because you're not running on Apple Silicon hardware"
                )

        return result

    def check_environment_variables(self) -> Dict[str, Any]:
        """Check relevant environment variables."""
        relevant_vars = [
            "CUDA_HOME",
            "CUDA_PATH",
            "CUDA_VISIBLE_DEVICES",
            "PYTORCH_CUDA_ALLOC_CONF",
            "HF_TOKEN",
            "OLLAMA_MODEL",
            "FLUX_MODEL",
            "LORA_DIR",
        ]

        result = {"variables": {}, "issues": []}

        for var in relevant_vars:
            value = os.environ.get(var)

            # Mask sensitive tokens
            if var == "HF_TOKEN" and value:
                # Show first 4 and last 4 characters, mask the rest
                if len(value) > 8:
                    masked_value = value[:4] + "*" * (len(value) - 8) + value[-4:]
                else:
                    masked_value = "****" + value[-4:] if len(value) > 4 else "****"
                result["variables"][var] = masked_value
            else:
                result["variables"][var] = value if value else "Not set"

            # Check for specific issues
            if var in ["CUDA_HOME", "CUDA_PATH"] and not value and torch.cuda.is_available():
                result["issues"].append(f"{var} is not set, but CUDA is available")

            if var == "HF_TOKEN" and value == "your_hugging_face_token_here":
                result["issues"].append("HF_TOKEN is set to default placeholder value")

        return result

    def check_system_resources(self) -> Dict[str, Any]:
        """Check system resources (RAM, disk space)."""
        result = {"memory": {}, "disk": {}, "issues": []}

        # Check memory
        vm = psutil.virtual_memory()
        result["memory"] = {
            "total": vm.total / (1024**3),  # GB
            "available": vm.available / (1024**3),  # GB
            "used_percent": vm.percent,
        }

        if vm.percent > 90:
            result["issues"].append(f"System memory usage is high ({vm.percent}%)")

        # Check disk space
        if self.config:
            paths_to_check = [
                self.config.system.output_dir,
                self.config.system.log_dir,
                self.config.system.cache_dir,
            ]

            for path in paths_to_check:
                try:
                    usage = shutil.disk_usage(path)
                    result["disk"][str(path)] = {
                        "total": usage.total / (1024**3),  # GB
                        "free": usage.free / (1024**3),  # GB
                        "used_percent": (usage.used / usage.total) * 100,
                    }

                    if (usage.free / usage.total) < 0.1:  # Less than 10% free
                        result["issues"].append(
                            f"Low disk space on {path} ({usage.free / (1024**3):.1f} GB free)"
                        )
                except Exception as e:
                    result["issues"].append(f"Failed to check disk space for {path}: {str(e)}")

        return result

    def check_dependencies(self) -> Dict[str, Any]:
        """Check for required external dependencies."""
        result = {"dependencies": {}, "issues": []}

        # Check for Ollama
        try:
            ollama_version = subprocess.check_output(
                ["ollama", "version"], stderr=subprocess.STDOUT, text=True
            ).strip()
            result["dependencies"]["ollama"] = ollama_version
        except (subprocess.SubprocessError, FileNotFoundError):
            result["dependencies"]["ollama"] = "Not found"
            result["issues"].append("Ollama not found in PATH. Required for prompt generation.")

        return result

    def determine_optimal_device(self) -> Tuple[Literal["cpu", "cuda", "mps"], List[str]]:
        """Determine the optimal device for running the application."""
        recommendations = []

        # Check for CUDA (NVIDIA GPUs)
        if torch.cuda.is_available():
            device = "cuda"
            gpu_name = torch.cuda.get_device_name(0)
            recommendations.append(f"Using NVIDIA GPU: {gpu_name}")

            # Check VRAM
            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            if vram_gb < 4:
                recommendations.append(
                    f"Warning: Low VRAM detected ({vram_gb:.1f} GB). Consider using smaller models or reducing batch size."
                )

        # Check for MPS (Apple Silicon)
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
            recommendations.append(f"Using Apple Silicon GPU: {platform.processor()}")

            # Check if we should use fp16
            if self.config and not self.config.system.mps_use_fp16:
                recommendations.append(
                    "Consider enabling mps_use_fp16 for better performance on Apple Silicon"
                )

        else:
            device = "cpu"
            recommendations.append(
                "No GPU acceleration available. Running on CPU will be significantly slower."
            )

            # Check if we're on Apple Silicon but MPS is not available
            if platform.processor() == "arm" and platform.system() == "Darwin":
                if hasattr(torch.backends, "mps") and torch.backends.mps.is_built():
                    recommendations.append(
                        "MPS is built but not available. Make sure you're using macOS 12.3+ and PyTorch 1.12+"
                    )
                else:
                    recommendations.append(
                        "You're on Apple Silicon but PyTorch was not built with MPS support. Consider reinstalling PyTorch."
                    )

        return device, recommendations

    def run_diagnostics(self) -> Dict[str, Any]:
        """Run all diagnostic checks and return results."""
        results = {
            "python": self.check_python_environment(),
            "torch": self.check_torch_installation(),
            "gpu": self.check_gpu_support(),
            "env_vars": self.check_environment_variables(),
            "system": self.check_system_resources(),
            "dependencies": self.check_dependencies(),
        }

        # Determine optimal device and get recommendations
        results["optimal_device"], results["recommendations"] = self.determine_optimal_device()

        # Collect all issues
        results["all_issues"] = []
        for section in ["python", "torch", "gpu", "env_vars", "system", "dependencies"]:
            results["all_issues"].extend(results[section]["issues"])

        return results

    def print_diagnostics(self, verbose: bool = False, check_env: bool = True):
        """Print formatted diagnostic information."""
        diagnostics = self.run_diagnostics()

        # Print header
        self.console.print(
            Panel.fit(
                "[bold green]System Diagnostics for Continuous Image Generator[/bold green]",
                border_style="green",
            )
        )

        # Print Python environment
        python_info = diagnostics["python"]
        self.console.print("\n[bold cyan]Python Environment[/bold cyan]")
        self.console.print(f"Python Version: {python_info['python_version'].split()[0]}")
        if verbose:
            self.console.print(f"Python Path: {python_info['python_path']}")
            self.console.print(f"Platform: {python_info['platform']}")
            self.console.print(f"Processor: {python_info['processor']}")
            self.console.print(f"Architecture: {python_info['architecture']}")
            if python_info["virtual_env"]:
                self.console.print(f"Virtual Environment: {python_info['virtual_env']}")

        # Print PyTorch information
        torch_info = diagnostics["torch"]
        self.console.print("\n[bold cyan]PyTorch Installation[/bold cyan]")
        self.console.print(f"PyTorch Version: {torch_info['torch_version']}")
        if verbose:
            self.console.print(f"PyTorch Path: {torch_info['torch_path']}")
            if torch_info["torch_config"]:
                self.console.print("\nBuild Configuration:")
                self.console.print(
                    Syntax(
                        torch_info["torch_config"],
                        "text",
                        theme="monokai",
                        background_color="default",
                    )
                )

        # Print GPU information
        gpu_info = diagnostics["gpu"]
        self.console.print("\n[bold cyan]GPU Support[/bold cyan]")

        if gpu_info["cuda_available"]:
            self.console.print(
                f"[green]✓[/green] CUDA available (version {gpu_info['cuda_version']})"
            )
            for device in gpu_info["cuda_devices"]:
                self.console.print(
                    f"  - GPU {device['index']}: {device['name']} ({device['memory']:.1f} GB)"
                )
        else:
            self.console.print("[red]✗[/red] CUDA not available")

        if hasattr(torch.backends, "mps"):
            if gpu_info["mps_available"]:
                self.console.print("[green]✓[/green] MPS available (Apple Silicon)")
            elif gpu_info["mps_built"]:
                self.console.print("[yellow]![/yellow] MPS is built but not available")
            else:
                self.console.print("[red]✗[/red] MPS not available")

        # Print environment variables if requested
        if check_env:
            env_info = diagnostics["env_vars"]
            self.console.print("\n[bold cyan]Environment Variables[/bold cyan]")

            env_table = Table(show_header=True, header_style="bold magenta")
            env_table.add_column("Variable")
            env_table.add_column("Value")

            for var, value in env_info["variables"].items():
                if value == "Not set":
                    env_table.add_row(var, f"[dim]{value}[/dim]")
                else:
                    env_table.add_row(var, value)

            self.console.print(env_table)

        # Print system resources
        sys_info = diagnostics["system"]
        self.console.print("\n[bold cyan]System Resources[/bold cyan]")

        mem = sys_info["memory"]
        self.console.print(
            f"Memory: {mem['available']:.1f} GB available / {mem['total']:.1f} GB total ({mem['used_percent']}% used)"
        )

        if verbose and sys_info["disk"]:
            self.console.print("\nDisk Space:")
            for path, usage in sys_info["disk"].items():
                self.console.print(
                    f"  - {path}: {usage['free']:.1f} GB free / {usage['total']:.1f} GB total ({usage['used_percent']:.1f}% used)"
                )

        # Print dependencies
        dep_info = diagnostics["dependencies"]
        self.console.print("\n[bold cyan]External Dependencies[/bold cyan]")

        for dep, status in dep_info["dependencies"].items():
            if status == "Not found":
                self.console.print(f"[red]✗[/red] {dep}: {status}")
            else:
                self.console.print(f"[green]✓[/green] {dep}: {status}")

        # Print issues and recommendations
        if diagnostics["all_issues"]:
            self.console.print("\n[bold red]Issues Detected[/bold red]")
            for i, issue in enumerate(diagnostics["all_issues"], 1):
                self.console.print(f"{i}. [yellow]{issue}[/yellow]")

        if diagnostics["recommendations"]:
            self.console.print("\n[bold green]Recommendations[/bold green]")
            for i, rec in enumerate(diagnostics["recommendations"], 1):
                self.console.print(f"{i}. {rec}")

        # Print summary
        self.console.print("\n[bold cyan]Summary[/bold cyan]")
        if diagnostics["optimal_device"] == "cuda":
            self.console.print("[green]✓ System has NVIDIA GPU with CUDA support[/green]")
        elif diagnostics["optimal_device"] == "mps":
            self.console.print("[green]✓ System has Apple Silicon with MPS support[/green]")
        else:
            self.console.print("[yellow]! No GPU acceleration available (CPU only)[/yellow]")

        if not diagnostics["all_issues"]:
            self.console.print("[green]✓ No issues detected[/green]")
        else:
            self.console.print(
                f"[yellow]! {len(diagnostics['all_issues'])} issues detected[/yellow]"
            )

    def suggest_fixes(self, diagnostics: Dict[str, Any]) -> List[str]:
        """Suggest fixes for common issues."""
        fixes = []

        for issue in diagnostics["all_issues"]:
            # Python version issues
            if "Python version" in issue and "below recommended" in issue:
                fixes.append("Upgrade Python to version 3.8 or higher")

            # PyTorch version issues
            elif "PyTorch version" in issue and "below recommended" in issue:
                fixes.append("Upgrade PyTorch to version 1.10 or higher")

            # CUDA issues
            elif "CUDA_HOME is not set" in issue or "CUDA_PATH is not set" in issue:
                fixes.append(
                    "Set CUDA_HOME and CUDA_PATH environment variables to your CUDA installation directory"
                )

            # MPS issues
            elif "MPS is built but not available" in issue:
                fixes.append("Ensure you're running macOS 12.3 or later")
                fixes.append("Make sure you're using PyTorch 1.12 or later with MPS support")

            # HF token issues
            elif "HF_TOKEN is set to default" in issue:
                fixes.append("Set a valid Hugging Face token in the HF_TOKEN environment variable")

            # Memory issues
            elif "System memory usage is high" in issue:
                fixes.append("Close unnecessary applications to free up memory")
                fixes.append("Consider reducing batch size or using a smaller model")

            # Disk space issues
            elif "Low disk space" in issue:
                fixes.append("Free up disk space by removing unnecessary files")
                fixes.append("Consider changing output directory to a drive with more space")

            # Ollama issues
            elif "Ollama not found" in issue:
                fixes.append("Install Ollama from https://ollama.ai/")
                fixes.append("Make sure Ollama is in your PATH")

        return fixes

    def fix_common_issues(self, diagnostics: Dict[str, Any]) -> List[str]:
        """Attempt to fix common issues automatically."""
        fixed = []

        # Create directories if they don't exist
        if self.config:
            for dir_attr in ["output_dir", "log_dir", "cache_dir"]:
                dir_path = getattr(self.config.system, dir_attr)
                try:
                    dir_path.mkdir(parents=True, exist_ok=True)
                    fixed.append(f"Created directory: {dir_path}")
                except Exception:
                    pass

        # Set optimal PyTorch settings based on device
        if diagnostics["optimal_device"] == "cuda":
            os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:512"
            fixed.append("Set optimal CUDA memory allocation configuration")

        elif diagnostics["optimal_device"] == "mps" and self.config:
            if not self.config.system.mps_use_fp16:
                # We can't modify the config directly here, but we can suggest it
                fixed.append(
                    "Consider setting mps_use_fp16=True in your configuration for better performance"
                )

        return fixed


def check_system() -> Dict[str, Any]:
    """
    Quick system check function that can be imported and used directly.

    Returns:
        Dict with system information
    """
    result = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "processor": platform.processor(),
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda if hasattr(torch.version, "cuda") else None,
        "mps_available": hasattr(torch.backends, "mps") and torch.backends.mps.is_available(),
    }

    # Add GPU details if available
    if result["cuda_available"]:
        result["device_type"] = "cuda"
        result["device_name"] = torch.cuda.get_device_name(0)
    elif result["mps_available"]:
        result["device_type"] = "mps"
        result["device_name"] = "Apple Silicon"
    else:
        result["device_type"] = "cpu"
        result["device_name"] = "CPU"

    return result
