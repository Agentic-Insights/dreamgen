# Windows Platform Notes

## UTF-8 Console Support

### Issue
Windows console (cmd.exe) by default uses CP1252 encoding which doesn't support Unicode emojis and special characters. This causes `UnicodeEncodeError` when trying to print emojis.

### Solutions

#### 1. Enable UTF-8 in Windows Terminal (Recommended)
Windows Terminal (available from Microsoft Store) supports UTF-8 by default. Use it instead of cmd.exe.

#### 2. Set System-Wide UTF-8 Support
1. Open Windows Settings → Time & Language → Language → Administrative language settings
2. Click "Change system locale..."
3. Check "Beta: Use Unicode UTF-8 for worldwide language support"
4. Restart computer

#### 3. Set Console Code Page Per Session
Run before starting the application:
```batch
chcp 65001
```

#### 4. Set Environment Variable
Add to system environment variables:
```batch
set PYTHONIOENCODING=utf-8
```

Or in PowerShell:
```powershell
$env:PYTHONIOENCODING = "utf-8"
```

#### 5. Configure Python to Use UTF-8
Add at the start of your Python session:
```python
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
```

### Application-Level Fix
The application has been modified to avoid using emojis in console output on Windows to prevent encoding issues. The web UI still displays emojis correctly as browsers handle UTF-8 natively.

### Rich Library Configuration
For the Rich console library, you can force plain text output:
```python
from rich.console import Console
console = Console(force_terminal=True, force_jupyter=False, legacy_windows=True)
```

## File Path Handling

Windows uses backslashes (`\`) for paths. The application uses `pathlib.Path` which handles this automatically, but be aware when:
- Passing paths as command line arguments
- Using paths in configuration files
- Working with Git (which uses forward slashes)

## GPU Support

### NVIDIA CUDA
- Install CUDA Toolkit from NVIDIA
- Install cuDNN
- PyTorch will automatically detect CUDA

### AMD GPUs
- Limited support through DirectML
- Not recommended for production use

## Process Management

### Background Tasks
Windows doesn't have native `nohup` or `&` for background processes. Use:
- Task Scheduler for persistent services
- `start /b` command for background execution
- Python's `subprocess` with `CREATE_NO_WINDOW` flag

## Development Tools

### Recommended Setup
1. **Terminal**: Windows Terminal or PowerShell 7+
2. **Shell**: PowerShell Core or Git Bash
3. **Package Manager**: `uv` works natively on Windows
4. **IDE**: VS Code with Python extension

### Known Issues
1. Long path support: Enable via Group Policy or registry
2. Case sensitivity: Windows is case-insensitive, Linux is case-sensitive
3. Line endings: Configure Git to handle CRLF/LF conversion

## Testing

Run tests with proper encoding:
```batch
set PYTHONIOENCODING=utf-8 && uv run pytest tests/
```

Or in PowerShell:
```powershell
$env:PYTHONIOENCODING = "utf-8"; uv run pytest tests/
```
