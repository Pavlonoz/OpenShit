import json
import subprocess
import sys
import time
import threading
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich.layout import Layout
from rich.live import Live
from rich import box
from rich.columns import Columns

console = Console()

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.json"
TOKENS_PATH = ROOT / "tokens.json"


def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def banner():
    console.print()
    console.print(Panel(
        " ______                                  ______   __        __    __\n"
        "/      \\                                /      \\ /  |      /  |  /  |\n"
        "/$$$$$$  |  ______    ______   _______  /$$$$$$  |$$ |____  $$/  _$$ |_\n"
        "$$ |  $$ | /      \\  /      \\ /       \\ $$ \\__$$/ $$      \\ /  |/ $$   |\n"
        "$$ |  $$ |/$$$$$$  |/$$$$$$  |$$$$$$$  |$$      \\ $$$$$$$  |$$ |$$$$$$/\n"
        "$$ |  $$ |$$ |  $$ |$$    $$ |$$ |  $$ | $$$$$$  |$$ |  $$ |$$ |  $$ | __\n"
        "$$ \\__$$ |$$ |__$$ |$$$$$$$$/ $$ |  $$ |/  \\__$$ |$$ |  $$ |$$ |  $$ |/  |\n"
        "$$    $$/ $$    $$/ $$       |$$ |  $$ |$$    $$/ $$ |  $$ |$$ |  $$  $$/\n"
        " $$$$$$/  $$$$$$$/   $$$$$$$/ $$/   $$/  $$$$$$/  $$/   $$/ $$/    $$$$/\n"
        "          $$ |\n"
        "          $$ |\n"
        "          $$/\n"
        "               made by Pavlonoz <3",
        border_style="cyan",
        padding=(1, 2),
        subtitle="[dim]Openference Token Rotator[/]",
        subtitle_align="right",
    ))
    res_file = ROOT / "residential_proxies.txt"
    if not res_file.exists():
        console.print("[yellow]No residential_proxies.txt found![/]")
        console.print("[dim]Get free residential proxies: https://webshare.io[/]")
        console.print("[dim]Format: ip:port:user:pass (one per line)[/]")
        console.print()


def show_status():
    if not TOKENS_PATH.exists():
        console.print("[yellow]No tokens generated yet.[/]")
        return

    tokens = load_json(TOKENS_PATH)
    if not tokens:
        console.print("[yellow]No tokens generated yet.[/]")
        return

    table = Table(title="Token Inventory", box=box.ROUNDED, border_style="cyan")
    table.add_column("#", style="dim", width=4)
    table.add_column("Email", style="cyan")
    table.add_column("Plan", style="green")
    table.add_column("Weekly", justify="right")
    table.add_column("Window", justify="right")
    table.add_column("RPM", justify="right")
    table.add_column("Created", style="dim")

    total_weekly = 0
    for i, t in enumerate(tokens):
        weekly = t.get("requests_per_week", 0) or 0
        total_weekly += weekly
        table.add_row(
            str(i + 1),
            t.get("email", "?"),
            t.get("plan", "?"),
            str(weekly),
            f'{t.get("requests_per_window", "?")}/{t.get("window_hours", "?")}h',
            str(t.get("max_rpm", "?")),
            t.get("created_at", "?")[:10],
        )

    console.print(table)
    console.print(f"[bold green]{len(tokens)} accounts[/] | [bold cyan]{total_weekly} combined weekly requests[/]")
    console.print(f"[dim]Data: {TOKENS_PATH}[/]\n")


def generate_tokens():
    config = load_json(CONFIG_PATH)
    count = config.get("account_count", 5)
    start = config.get("start_index", 1)
    prefix = config.get("email_base", "user").split("@")[0]

    console.print(f"\n[bold]Will create [cyan]{count}[/] accounts using temp emails: [cyan]{prefix}{start}@*.tm[/] ...[/]")
    if not Confirm.ask("Proceed?", default=True):
        return

    console.print("\n[bold yellow]Running token manager...[/]\n")
    result = subprocess.run(
        [sys.executable, str(ROOT / "token_manager.py")],
        cwd=str(ROOT),
        capture_output=False,
    )
    if result.returncode == 0:
        console.print("\n[bold green]Done![/]")
        show_status()
    else:
        console.print("\n[red]Token generation failed.[/]")


def configure():
    config = load_json(CONFIG_PATH)
    console.print(Panel("[bold]Current Configuration[/]", border_style="blue"))
    for key, val in config.items():
        if "password" in key.lower() and val:
            display = val[:4] + "****"
        else:
            display = str(val)
        console.print(f"  [cyan]{key}[/]: [white]{display}[/]")

    console.print()
    if Confirm.ask("Edit configuration?", default=False):
        console.print("\n[bold]Available settings to change:[/]")
        console.print("  [cyan]email_base[/]       - Username prefix for temp emails (e.g. myuser)")
        console.print("  [cyan]account_password[/] - Password for all Openference accounts")
        console.print("  [cyan]account_count[/]    - How many accounts to create")
        console.print("  [cyan]start_index[/]      - Starting number for temp email index")
        console.print("  [cyan]proxy_port[/]       - Port for local proxy (default 8787)")
        console.print()

        for key in ["email_base", "account_password", "account_count", "start_index", "proxy_port"]:
            if key in config:
                current = config[key]
                mask = "****" if "password" in key.lower() and current else str(current)
                new = Prompt.ask(f"  {key}", default=str(current), password="password" in key.lower())
                try:
                    if key in ("account_count", "start_index", "proxy_port"):
                        config[key] = int(new)
                    else:
                        config[key] = new
                except ValueError:
                    pass

        save_json(CONFIG_PATH, config)
        console.print("[green]Configuration saved.[/]")


def start_proxy():
    if not TOKENS_PATH.exists() or not load_json(TOKENS_PATH):
        config = load_json(CONFIG_PATH)
        if config.get("auto_generate", True):
            console.print("[yellow]No tokens yet, but auto-generation is ON. The proxy will create accounts automatically.[/]")
        else:
            console.print("[red]No tokens and auto-generation is OFF. Enable it in config or generate tokens first (option 2).[/]")
            return

    config = load_json(CONFIG_PATH)
    port = config.get("proxy_port", 8787)
    host = config.get("proxy_host", "127.0.0.1")

    console.print(f"\n[bold green]Starting proxy on http://{host}:{port}[/]")
    console.print("[dim]Status dashboard: http://{}:{}/[/]".format(host, port))
    console.print("[dim]Press Ctrl+C to stop the proxy[/]\n")

    server = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "proxy.py")],
        cwd=str(ROOT),
    )
    try:
        import requests
        started = False
        for retry in range(5):
            time.sleep(2)
            try:
                r = requests.get(f"http://{host}:{port}/api/proxy/status", timeout=3)
                if r.status_code == 200:
                    console.print("[green]Proxy is running![/]")
                    started = True
                    break
            except Exception:
                pass
        if not started:
            console.print("[red]Proxy failed to start. Check proxy.py output above for errors.[/]")
            server.terminate()
            return

        console.print("\n[bold]Quick setup for Claude Code:[/]")
        console.print(f"  [cyan]set ANTHROPIC_BASE_URL=http://{host}:{port}/v1[/]")
        console.print(f"  [cyan]set ANTHROPIC_API_KEY=anything[/]")
        console.print("\n[dim]Proxy running. Press Ctrl+C to stop.[/]")
        server.wait()
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopping proxy...[/]")
        server.terminate()
        server.wait()
        console.print("[green]Proxy stopped.[/]")


def quick_check():
    console.print("[bold]Checking Openference API connectivity...[/]")
    import requests
    try:
        r = requests.get("https://api.openference.com/v1/models", timeout=10)
        console.print(f"  API: [green]reachable[/] ({r.status_code})")
    except Exception as e:
        console.print(f"  API: [red]unreachable[/] - {e}")

    if TOKENS_PATH.exists():
        tokens = load_json(TOKENS_PATH)
        console.print(f"  Tokens: [green]{len(tokens)} loaded[/]")
    else:
        console.print(f"  Tokens: [yellow]none[/]")

    config = load_json(CONFIG_PATH)
    pw = config.get("email_password", "")
    if pw and pw != "YOUR_GMAIL_APP_PASSWORD_HERE":
        console.print("  Gmail: [green]configured[/]")
    else:
        console.print("  Gmail: [red]not configured[/]")


def main():
    banner()

    while True:
        console.print()
        table = Table(show_header=False, box=None, padding=(0, 4))
        table.add_column(style="bold cyan", width=3)
        table.add_column()
        table.add_row("1", "[bold]Start Proxy Server[/]  [dim](launch the rotating proxy)[/]")
        table.add_row("2", "[bold]Generate API Tokens[/]  [dim](create accounts + tokens)[/]")
        table.add_row("3", "[bold]View Token Status[/]  [dim](show all tokens & limits)[/]")
        table.add_row("4", "[bold]Configure Settings[/]  [dim](edit emails, passwords, ports)[/]")
        table.add_row("5", "[bold]Quick Health Check[/]  [dim](test connectivity)[/]")
        table.add_row("0", "[bold red]Exit[/]")
        console.print(Panel(table, border_style="cyan", padding=(1, 2)))

        choice = Prompt.ask("Select", choices=["0", "1", "2", "3", "4", "5"], default="1")

        if choice == "0":
            console.print("[dim]Goodbye![/]")
            break
        elif choice == "1":
            start_proxy()
        elif choice == "2":
            generate_tokens()
        elif choice == "3":
            show_status()
        elif choice == "4":
            configure()
        elif choice == "5":
            quick_check()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[dim]Exiting...[/]")
    except Exception as e:
        console.print(f"\n[red]Error: {e}[/]")
