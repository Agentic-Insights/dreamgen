"""
Memory management utilities for GPU operations.
"""

import gc
import os
import platform
import time
from typing import Literal

import psutil
import torch


class MemoryManager:
    def __init__(self, device: Literal["cpu", "cuda", "mps"] = "cuda"):
        self.device = device
        self.warning_threshold = 0.8  # 80% memory usage warning
        self.critical_threshold = 0.9  # 90% memory usage critical
        self.is_apple_silicon = platform.processor() == "arm" and platform.system() == "Darwin"

    def get_gpu_memory_info(self) -> tuple[float, float, float]:
        """Get current GPU memory usage information."""
        # For CUDA devices
        if self.device == "cuda" and torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated() / 1024**3
            reserved = torch.cuda.memory_reserved() / 1024**3
            total = torch.cuda.get_device_properties(0).total_memory / 1024**3
            return allocated, reserved, total

        # For MPS devices (Apple Silicon)
        # MPS doesn't have built-in memory tracking like CUDA
        # We'll use system memory as a proxy for unified memory architecture
        if (
            self.device == "mps"
            and hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available()
        ):
            # On Apple Silicon, GPU memory is shared with system memory
            # We'll use a portion of system memory as an estimate
            vm = psutil.virtual_memory()
            # Estimate GPU memory usage based on process memory
            process = psutil.Process(os.getpid())
            process_memory = process.memory_info().rss / 1024**3

            # For Apple Silicon, we'll use system memory as a proxy
            # This is an approximation since MPS doesn't expose detailed memory stats
            return process_memory, process_memory, vm.total / 1024**3

        return 0.0, 0.0, 0.0

    def get_system_memory_info(self) -> tuple[float, float]:
        """Get system memory usage information."""
        vm = psutil.virtual_memory()
        return vm.used / 1024**3, vm.total / 1024**3

    def check_memory_pressure(self) -> tuple[bool, str]:
        """
        Check both GPU and system memory pressure.

        Returns:
            tuple[bool, str]: (is_critical, status_message)
        """
        if self.device in ["cuda", "mps"]:
            allocated, reserved, total = self.get_gpu_memory_info()
            if total > 0:  # Ensure we have valid GPU memory info
                gpu_usage = allocated / total

                if gpu_usage > self.critical_threshold:
                    return True, f"Critical GPU memory pressure: {gpu_usage:.1%} used"
                elif gpu_usage > self.warning_threshold:
                    return False, f"High GPU memory pressure: {gpu_usage:.1%} used"

        sys_used, sys_total = self.get_system_memory_info()
        sys_usage = sys_used / sys_total

        if sys_usage > self.critical_threshold:
            return True, f"Critical system memory pressure: {sys_usage:.1%} used"
        elif sys_usage > self.warning_threshold:
            return False, f"High system memory pressure: {sys_usage:.1%} used"

        return False, "Memory usage normal"

    def optimize_memory_usage(self):
        """Optimize memory usage through various techniques."""
        if self.device == "cuda":
            # Clear CUDA cache
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
        elif (
            self.device == "mps"
            and hasattr(torch.backends, "mps")
            and torch.backends.mps.is_available()
        ):
            # MPS doesn't have explicit cache clearing functions like CUDA
            # But we can still help with general memory management
            pass

        # Run garbage collection
        gc.collect()

        # Suggest to OS to release memory
        if hasattr(os, "malloc_trim"):  # Linux only
            os.malloc_trim(0)

    def wait_for_memory_release(self, timeout: int = 30):
        """
        Wait for memory pressure to decrease.

        Args:
            timeout: Maximum seconds to wait
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            is_critical, _ = self.check_memory_pressure()
            if not is_critical:
                return
            self.optimize_memory_usage()
            time.sleep(1)
