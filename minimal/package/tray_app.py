import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from tkinter import Tk, messagebox, simpledialog

import pystray
import requests
from PIL import Image, ImageDraw


APP_NAME = "Local Router Minimal"
BASE_URL = "http://127.0.0.1:8000"
API_BASE_URL = f"{BASE_URL}/v1"


def runtime_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    path = Path(root) / "LocalRouterMinimal"
    path.mkdir(parents=True, exist_ok=True)
    return path


RUNTIME_DIR = runtime_dir()
MODEL_PATH = RUNTIME_DIR / "model.gguf"
ENV_PATH = RUNTIME_DIR / "server.env"
LOG_PATH = RUNTIME_DIR / "server.log"
PID_PATH = RUNTIME_DIR / "server.pid"


def server_code_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[1]


def server_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--server"]
    return [sys.executable, str(Path(__file__).resolve()), "--server"]


def server_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "MODEL_PATH": str(MODEL_PATH),
            "MODEL_ID": read_env_value("MODEL_ID", "local-gguf"),
            "N_CTX": read_env_value("N_CTX", "4096"),
            "N_GPU_LAYERS": read_env_value("N_GPU_LAYERS", "-1"),
            "HOST": "127.0.0.1",
            "PORT": "8000",
            "PYTHONPATH": str(server_code_dir()),
        }
    )
    return env


def read_env_value(key: str, default: str) -> str:
    if not ENV_PATH.exists():
        return default
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return default


def write_env(model_id: str = "local-gguf") -> None:
    ENV_PATH.write_text(
        "\n".join(
            [
                f"MODEL_PATH={MODEL_PATH}",
                f"MODEL_ID={model_id}",
                "N_CTX=4096",
                "N_GPU_LAYERS=-1",
                "HOST=127.0.0.1",
                "PORT=8000",
                "",
            ]
        ),
        encoding="utf-8",
    )


def hidden_root() -> Tk:
    root = Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    return root


def info(title: str, text: str) -> None:
    root = hidden_root()
    try:
        messagebox.showinfo(title, text, parent=root)
    finally:
        root.destroy()


def error(title: str, text: str) -> None:
    root = hidden_root()
    try:
        messagebox.showerror(title, text, parent=root)
    finally:
        root.destroy()


def ask_text(title: str, prompt: str, initial: str = "") -> str | None:
    root = hidden_root()
    try:
        return simpledialog.askstring(title, prompt, initialvalue=initial, parent=root)
    finally:
        root.destroy()


def download_model(url: str) -> None:
    partial = MODEL_PATH.with_suffix(".gguf.download")
    existing = partial.stat().st_size if partial.exists() else 0
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    mode = "ab" if existing else "wb"

    with requests.get(url, headers=headers, stream=True, timeout=30) as response:
        if response.status_code == 416:
            partial.replace(MODEL_PATH)
            return
        response.raise_for_status()
        if existing and response.status_code != 206:
            existing = 0
            mode = "wb"
        with partial.open(mode) as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)

    partial.replace(MODEL_PATH)


def ensure_model() -> bool:
    if MODEL_PATH.exists() and ENV_PATH.exists():
        return True

    url = ask_text("Download model", "Paste a direct GGUF model URL:")
    if not url:
        return False
    model_id = ask_text("Model name", "Model name shown to clients:", "local-gguf") or "local-gguf"

    try:
        info("Download started", "The model download will run now. This can take several minutes.")
        download_model(url.strip())
        write_env(model_id.strip() or "local-gguf")
        info("Download complete", f"Model saved to:\n{MODEL_PATH}")
        return True
    except Exception as exc:
        error("Download failed", str(exc))
        return False


def current_status() -> str:
    try:
        response = requests.get(f"{BASE_URL}/readyz", timeout=2)
        if response.status_code == 200:
            return "ready"
        return f"not ready: HTTP {response.status_code}"
    except requests.RequestException:
        return "stopped"


def start_server() -> None:
    if not ensure_model():
        return
    if current_status() == "ready":
        info(APP_NAME, f"Already running:\n{API_BASE_URL}")
        return

    log = LOG_PATH.open("ab")
    process = subprocess.Popen(
        server_command(),
        cwd=str(server_code_dir()),
        env=server_env(),
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    PID_PATH.write_text(str(process.pid), encoding="utf-8")

    for _ in range(90):
        status = current_status()
        if status == "ready":
            info(APP_NAME, f"Server is ready:\n{API_BASE_URL}")
            return
        if process.poll() is not None:
            error(APP_NAME, f"Server exited early. Open logs:\n{LOG_PATH}")
            return
        time.sleep(1)
    info(APP_NAME, f"Server started but is still loading. Logs:\n{LOG_PATH}")


def stop_server() -> None:
    if PID_PATH.exists():
        try:
            subprocess.run(
                ["taskkill", "/PID", PID_PATH.read_text(encoding="utf-8").strip(), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        finally:
            PID_PATH.unlink(missing_ok=True)
    info(APP_NAME, "Server stopped.")


def show_status() -> None:
    info(APP_NAME, f"Status: {current_status()}\nAPI base URL:\n{API_BASE_URL}")


def copy_base_url() -> None:
    root = hidden_root()
    try:
        root.clipboard_clear()
        root.clipboard_append(API_BASE_URL)
        root.update()
        messagebox.showinfo(APP_NAME, "API base URL copied.", parent=root)
    finally:
        root.destroy()


def open_logs() -> None:
    LOG_PATH.touch(exist_ok=True)
    os.startfile(str(LOG_PATH))


def open_runtime_folder() -> None:
    os.startfile(str(RUNTIME_DIR))


def create_icon() -> Image.Image:
    image = Image.new("RGB", (64, 64), "#1f2937")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((10, 10, 54, 54), radius=10, fill="#10b981")
    draw.rectangle((18, 25, 46, 31), fill="#f9fafb")
    draw.rectangle((18, 36, 38, 42), fill="#f9fafb")
    return image


def threaded(action):
    def wrapped(icon, item=None):
        threading.Thread(target=action, daemon=True).start()

    return wrapped


def run_tray() -> None:
    menu = pystray.Menu(
        pystray.MenuItem("Start server", threaded(start_server)),
        pystray.MenuItem("Stop server", threaded(stop_server)),
        pystray.MenuItem("Status", threaded(show_status)),
        pystray.MenuItem("Copy API base URL", threaded(copy_base_url)),
        pystray.MenuItem("Open logs", threaded(open_logs)),
        pystray.MenuItem("Open data folder", threaded(open_runtime_folder)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", lambda icon, item: icon.stop()),
    )
    icon = pystray.Icon(APP_NAME, create_icon(), APP_NAME, menu)
    icon.run()


def run_server_mode() -> None:
    sys.path.insert(0, str(server_code_dir()))
    import uvicorn

    uvicorn.run(
        "api_server:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        log_level="info",
    )


if __name__ == "__main__":
    if "--server" in sys.argv:
        run_server_mode()
    else:
        run_tray()
