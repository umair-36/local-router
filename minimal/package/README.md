# Local Router Minimal Windows Package

This folder is a Windows packaging attempt for the minimal local router. It creates a tray app that downloads a GGUF model, starts/stops the local API server, shows status, opens logs, and copies the OpenAI-compatible base URL.

## Run From Source

Open PowerShell in this folder and run:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\run_dev_windows.ps1
```

Use the tray icon to start the server. On first start, paste a direct `.gguf` model URL.

## Build An Executable

Open PowerShell in this folder and run:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

The executable should be created at:

```text
dist\LocalRouterMinimal\LocalRouterMinimal.exe
```

## Optional Installer

After building the executable, install Inno Setup and compile `installer.iss`. The installer will package the PyInstaller output.

## Runtime Data

The tray app stores model, logs, and config here:

```text
%LOCALAPPDATA%\LocalRouterMinimal
```

The API base URL is:

```text
http://127.0.0.1:8000/v1
```

Readiness check:

```text
http://127.0.0.1:8000/readyz
```
