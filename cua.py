"""Let Claude Opus 5.5 drive a real Linux desktop with Anthropic's computer use toolset.

    python cua.py "Open Firefox and search for Anthropic"       # our loop, local Docker desktop
    python cua.py "Open a terminal and run htop" --orgo         # our loop, Orgo cloud computer
    python cua.py "Open a terminal and run htop" --orgo-agent   # Orgo's hosted loop, Orgo cloud computer
"""

import argparse
import base64
import io
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

import anthropic
import requests
from dotenv import load_dotenv
from PIL import Image
from rich.console import Console
from rich.panel import Panel

load_dotenv()
console = Console()

SYSTEM = """You control a Linux desktop through screenshots, mouse and keyboard.
A terminal and a web browser are installed; open them from the dock or taskbar.
End each group of actions with a screenshot so you can check the result. Ask before anything irreversible."""

BUTTONS = {"left_click": (1, 1), "right_click": (3, 1), "middle_click": (2, 1), "double_click": (1, 2), "triple_click": (1, 3)}
SCROLL = {"up": 4, "down": 5, "left": 6, "right": 7}


class Docker:
    """The local desktop from compose.yaml. Actions run as `docker exec ... xdotool`."""

    def __init__(self, container="claude-desktop"):
        self.container = container
        self.watch_url = "http://localhost:6080/vnc.html?autoconnect=1&resize=scale"
        try:
            self.xdo("getmouselocation")
        except (RuntimeError, FileNotFoundError):
            raise SystemExit("Desktop not running. Start it with: docker compose up -d --build")

    def _exec(self, *args) -> bytes:
        cmd = ["docker", "exec", "-e", "DISPLAY=:99", self.container, *map(str, args)]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f"{args[0]} failed: {result.stderr.decode().strip()}")
        return result.stdout

    def xdo(self, *args) -> str:
        return self._exec("xdotool", *args).decode()

    def screenshot(self) -> bytes:
        return self._exec("import", "-window", "root", "png:-")

    def close(self):
        pass  # The container keeps running so you can look around; `docker compose down` stops it.


class Orgo:
    """A fresh Orgo cloud computer (docs.orgo.ai). Actions run as xdotool through its bash endpoint."""

    API = "https://www.orgo.ai/api"

    def __init__(self, keep=False, name=None, computer_id=None):
        self.keep = keep or bool(computer_id)  # Never delete a computer we didn't create.
        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {os.environ['ORGO_API_KEY']}"
        if computer_id:
            self.id = computer_id
            self.watch_url = self._call("GET", f"/computers/{computer_id}").get("connection_url", "")
            return
        workspace = os.getenv("ORGO_WORKSPACE_ID") or self._call("GET", "/workspaces")["workspaces"][0]["id"]
        with console.status("Booting an Orgo computer…"):
            pc = self._call("POST", "/computers", json={
                "workspace_id": workspace, "name": name or f"cua-{int(time.time())}", "ram": 4, "cpu": 1,
                "billing_mode": os.getenv("ORGO_BILLING_MODE", "plan"),  # "hourly" for free-credit accounts
            })
            self.id = pc["id"]
            for _ in range(60):
                if pc["status"] in ("running", "error"):
                    break
                time.sleep(2)
                pc = self._call("GET", f"/computers/{self.id}")
            if pc["status"] != "running":
                self._call("DELETE", f"/computers/{self.id}")
                raise SystemExit(f"Orgo computer did not start (status: {pc['status']}).")
        self.watch_url = pc.get("connection_url") or "https://www.orgo.ai/workspaces"

    def _call(self, method, path, **kwargs):
        r = self.http.request(method, self.API + path, timeout=60, **kwargs)
        if not r.ok:
            raise SystemExit(f"Orgo API error {r.status_code} on {method} {path}: {r.text[:300]}")
        return r.json()

    def xdo(self, *args) -> str:
        out = self._call("POST", f"/computers/{self.id}/bash", json={"command": shlex.join(["xdotool", *map(str, args)])})
        if out.get("exit_code"):
            raise RuntimeError(f"xdotool failed: {out.get('output', '').strip()}")
        return out.get("output", "")

    def screenshot(self) -> bytes:
        shot = self._call("GET", f"/computers/{self.id}/screenshot", params={"response_format": "base64", "format": "png"})
        return base64.b64decode(shot["image"])

    def close(self):
        if not self.keep:
            self._call("DELETE", f"/computers/{self.id}")
        console.print(f"[dim]Orgo computer {self.id} {'kept running' if self.keep else 'deleted'}.[/]")


def zoom(png: bytes, region) -> bytes:
    """Crop a region and scale it up to the screenshot's size, keeping the aspect ratio."""
    image = Image.open(io.BytesIO(png))
    crop = image.crop(tuple(region))
    scale = min(image.width / crop.width, image.height / crop.height)
    out = io.BytesIO()
    crop.resize((round(crop.width * scale), round(crop.height * scale))).save(out, "PNG")
    return out.getvalue()


def keys(combo: str) -> str:
    # Lowercase letters in combos: to xdotool, "ctrl+L" means ctrl+shift+l.
    parts = combo.split("+")
    return "+".join(p.lower() if len(p) == 1 and len(parts) > 1 else p for p in parts)


def act(computer, name: str, i: dict):
    """Run one computer toolset member. Returns PNG bytes for screenshot/zoom, text otherwise."""
    mods = i["text"].split("+") if i.get("text") and name != "type" else []
    down = [arg for m in mods for arg in ("keydown", m)]
    up = [arg for m in reversed(mods) for arg in ("keyup", m)]
    move = ["mousemove", *i["coordinate"]] if i.get("coordinate") else []
    match name:
        case "screenshot":
            return computer.screenshot()
        case "zoom":
            return zoom(computer.screenshot(), i["region"])
        case "left_click" | "right_click" | "middle_click" | "double_click" | "triple_click":
            button, repeat = BUTTONS[name]
            computer.xdo(*move, *down, "click", "--repeat", repeat, button, *up)
        case "left_click_drag":
            computer.xdo("mousemove", *i["start_coordinate"], *down, "mousedown", 1, *move, "mouseup", 1, *up)
        case "mouse_move":
            computer.xdo(*move)
        case "left_mouse_down" | "left_mouse_up":
            computer.xdo("mousedown" if name == "left_mouse_down" else "mouseup", 1)
        case "cursor_position":
            pos = dict(line.split("=") for line in computer.xdo("getmouselocation", "--shell").split())
            return f"X={pos['X']}, Y={pos['Y']}"
        case "scroll":
            button = SCROLL[i["scroll_direction"]]
            computer.xdo(*move, *down, "click", "--repeat", i.get("scroll_amount", 3), button, *up)
        case "type":
            computer.xdo("type", "--delay", 10, "--", i["text"])
        case "key":
            computer.xdo("key", "--repeat", i.get("repeat", 1), "--", keys(i["text"]))
        case "hold_key":
            computer.xdo("keydown", keys(i["text"]))
            time.sleep(i["duration"])
            computer.xdo("keyup", keys(i["text"]))
        case "wait":
            time.sleep(i["duration"])
        case _:
            raise ValueError(f"Unsupported action: {name}")
    return "OK"


def result(call, output=None, error=None) -> dict:
    block = {"type": "tool_result", "tool_use_id": call.id, "toolset_name": "computer"}
    if error:
        return {**block, "is_error": True, "content": error}
    if isinstance(output, bytes):
        data = base64.b64encode(output).decode()
        return {**block, "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}}]}
    return {**block, "content": [{"type": "text", "text": output}]}


def run(task: str, computer, model: str, max_steps: int, fast: bool = False, effort: str = "medium"):
    client = anthropic.Anthropic()
    shots = Path("runs") / time.strftime("%Y%m%d-%H%M%S")
    shots.mkdir(parents=True)
    request = dict(
        model=model, max_tokens=16000, system=SYSTEM, tools=[{"type": "computer_toolset_20260801"}],
        thinking={"type": "adaptive", "display": "updates"},  # Short progress notes between actions.
        output_config={"effort": effort},
        cache_control={"type": "ephemeral"},  # Each turn re-sends the history; caching makes that cheap.
        fallbacks="default",  # If a safety classifier declines, retry on a fallback model.
        betas=["thinking-display-updates-2026-08-18", "server-side-fallback-2026-07-01"],
    )
    if fast:  # Fast mode: up to 2.5x faster output, billed at 2x.
        request["speed"] = "fast"
        request["betas"].append("fast-mode-2026-02-01")

    console.print(Panel(task, title=f"[bold]{model}{' ⚡ fast' if fast else ''}[/]", subtitle=f"watch live: {computer.watch_url}"))
    messages = [{"role": "user", "content": task}]
    step = 0
    for _ in range(max_steps):
        response = client.beta.messages.create(**request, messages=messages)
        if response.stop_reason == "refusal":
            raise SystemExit(f"Claude declined: {response.stop_details.explanation if response.stop_details else ''}")
        messages.append({"role": "assistant", "content": response.content})  # Keep thinking blocks as-is.

        calls = []
        for block in response.content:
            if block.type == "thinking" and block.thinking:
                console.print(f"[italic dim]💭 {block.thinking.strip()}[/]")
            elif block.type == "tool_use" and block.toolset_name == "computer":
                calls.append(block)
        if not calls:  # No more actions: Claude is done.
            text = "".join(b.text for b in response.content if b.type == "text")
            console.print(Panel(text or "(no answer)", title="✅ Done", border_style="green"))
            console.print(f"[dim]Screenshots saved to {shots}/[/]")
            return

        # Run the batch in order. After a failure, skip the rest (Anthropic's documented halt text).
        results, failed = [], False
        for call in calls:
            step += 1
            args = " ".join(f"[dim]{k}=[/]{json.dumps(v)}" for k, v in call.input.items())
            console.print(f"  [dim]{step:>2}[/] [bold cyan]{call.name}[/] {args}")
            if failed:
                results.append(result(call, error="Not executed: an earlier computer action in this turn failed."))
                continue
            try:
                output = act(computer, call.name, call.input)
                if isinstance(output, bytes):
                    (shots / f"{step:02}-{call.name}.png").write_bytes(output)
                results.append(result(call, output))
            except Exception as e:
                failed = True
                console.print(f"     [red]✗ {e}[/]")
                results.append(result(call, error=str(e)))
        messages.append({"role": "user", "content": results})

    console.print(f"[yellow]Stopped after {max_steps} turns.[/]")


def run_orgo_agent(task: str, computer: Orgo, model: str):
    """Hand the whole loop to Orgo: one streaming call, and Claude runs on Orgo's side."""
    console.print(Panel(task, title=f"[bold]{model}[/]", subtitle=f"watch live: {computer.watch_url}"))
    headers = {"Authorization": f"Bearer {os.environ['ORGO_API_KEY']}"}
    body = {"model": model, "computer_id": computer.id, "stream": True, "messages": [{"role": "user", "content": task}]}
    with requests.post(f"{Orgo.API}/v1/chat/completions", headers=headers, json=body, stream=True, timeout=None) as r:
        if not r.ok:
            raise SystemExit(f"Orgo API error {r.status_code}: {r.text[:300]}")
        r.encoding = "utf-8"  # The stream has no charset, so requests would guess Latin-1.
        for line in r.iter_lines(decode_unicode=True):
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            chunk = json.loads(line[6:])
            if "error" in chunk:
                raise SystemExit(f"Orgo agent error: {chunk['error'].get('message')}")
            text = chunk["choices"][0]["delta"].get("content") if chunk.get("choices") else None
            if text:
                console.print(text, end="", markup=False, highlight=False)
    console.print("\n[bold green]✅ Done[/]")


def main():
    parser = argparse.ArgumentParser(description="Let Claude use a computer.")
    parser.add_argument("task", nargs="?", default="Open Firefox, go to anthropic.com and tell me the top headline.")
    parser.add_argument("--orgo", action="store_true", help="use an Orgo cloud computer instead of Docker")
    parser.add_argument("--orgo-agent", action="store_true", help="let Orgo run the loop (no Anthropic key needed)")
    parser.add_argument("--keep", action="store_true", help="keep the Orgo computer running afterwards")
    parser.add_argument("--name", help="name for the new Orgo computer")
    parser.add_argument("--computer", help="reuse an existing Orgo computer by ID instead of creating one")
    parser.add_argument("--model", default=os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5"))
    parser.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--max-steps", type=int, default=30, help="max model turns (each can batch several actions)")
    parser.add_argument("--fast", action="store_true", help="Claude Fast mode: quicker, 2x the price")
    args = parser.parse_args()

    cloud = args.orgo or args.orgo_agent or bool(args.computer)
    for key in ([] if args.orgo_agent else ["ANTHROPIC_API_KEY"]) + (["ORGO_API_KEY"] if cloud else []):
        if not os.getenv(key):
            raise SystemExit(f"Missing {key}. Copy .env.example to .env and fill it in.")

    computer = Orgo(keep=args.keep, name=args.name, computer_id=args.computer) if cloud else Docker()
    try:
        if args.orgo_agent:
            run_orgo_agent(args.task, computer, os.getenv("ORGO_AGENT_MODEL", "claude-opus-5.5"))
        else:
            run(args.task, computer, args.model, args.max_steps, args.fast, args.effort)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/]")
    except anthropic.APIStatusError as e:
        console.print(f"[bold red]Anthropic API error {e.status_code}:[/] {e.message}")
    finally:
        computer.close()


if __name__ == "__main__":
    main()
