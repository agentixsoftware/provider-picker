"""Terminal launcher for Claude Code and Codex."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "provider-picker"
CONFIG = ROOT / "providers.json"
CACHE = ROOT / "catalogs.json"
COMMANDS = {"claude": "claude", "codex": "codex"}


def load(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def save(path, data):
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=ROOT, delete=False) as file:
        temp = Path(file.name)
        try:
            json.dump(data, file, indent=2)
            file.close()
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def checked_url(value):
    parsed = urlsplit(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Enter an HTTP(S) URL without embedded credentials.")
    return value


def catalog(profile):
    base = profile["base"]
    protocol = profile["catalog_auth"]
    url = profile["catalog_url"] or (
        base.rstrip("/") + ("/v1/models" if protocol == "anthropic" and not base.rstrip("/").endswith("/v1") else "/models")
    )
    key = profile["key"]
    headers = {"Accept": "application/json"}
    if protocol == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
        if key:
            headers["x-api-key"] = key
    elif key and protocol == "bearer":
        headers["Authorization"] = f"Bearer {key}"
    opener = build_opener(NoRedirect())
    with opener.open(Request(checked_url(url), headers=headers), timeout=5) as response:
        payload = json.loads(response.read(4_000_000))
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("Expected a list or a JSON object with a data list.")
    models = [row.get("id") if isinstance(row, dict) else row for row in rows]
    return sorted({model for model in models if isinstance(model, str) and model.isprintable() and model.strip()})


def prompt(label, current="", help_text=""):
    if help_text:
        print(help_text)
    value = input(f"{label}" + (f" [{current}]" if current else "") + ": ").strip()
    return current if not value else "" if value == "-" else value


def choose(title, options, searchable=False):
    visible = options
    while True:
        print(f"\n{title}")
        for number, (label, _) in enumerate(visible[:30], 1):
            print(f"  {number:2}. {label}")
        if len(visible) > 30:
            print(f"  Showing 30 of {len(visible)}. Search to narrow the list.")
        reply = input("Number or search (Enter to go back, / to reset): " if searchable
                      else "Number (Enter to go back): ").strip()
        if not reply:
            return None
        if reply.isdecimal() and 1 <= int(reply) <= min(30, len(visible)):
            return visible[int(reply) - 1][1]
        if searchable:
            query = "" if reply == "/" else reply.lstrip("/").casefold()
            visible = [option for option in options if query in option[0].casefold()]
        else:
            print("Choose a number from the menu.")


def edit(profile):
    updated = dict(profile)
    print("Press Enter to keep a value, or type - to clear an optional field.")
    updated["base"] = checked_url(prompt("Base URL", profile.get("base", ""),
                                         "Use the API base URL supplied by your provider."))
    updated["catalog_url"] = prompt("Catalog URL", profile.get("catalog_url", ""),
                                    "Optional. Leave blank to derive the models URL from the base URL.")
    if updated["catalog_url"]:
        checked_url(updated["catalog_url"])
    updated["catalog_auth"] = prompt("Catalog authentication (bearer, anthropic, none)",
                                     profile.get("catalog_auth", "bearer"))
    if updated["catalog_auth"] not in {"bearer", "anthropic", "none"}:
        raise ValueError("Choose bearer, anthropic, or none.")
    for harness, protocol in (("claude", "Anthropic Messages"), ("codex", "OpenAI Responses")):
        route = prompt(f"{harness} API base", profile.get(harness, ""),
                       f"Requires {protocol}. Type = to use the provider base URL.")
        if route and route != "=":
            checked_url(route)
        updated[harness] = route
    updated["claude_auth"] = prompt("Claude authentication (key or bearer)", profile.get("claude_auth", "key"))
    if updated["claude_auth"] not in {"key", "bearer"}:
        raise ValueError("Choose key or bearer.")
    updated["manual"] = prompt("Manual model IDs, comma separated", ",".join(profile.get("manual", [])))
    updated["manual"] = [value.strip() for value in updated["manual"].split(",") if value.strip()]
    key_status = "configured" if profile.get("key") else "empty"
    key = getpass.getpass(f"API key ({key_status}; Enter to keep, - to clear): ")
    updated["key"] = profile.get("key", "") if not key else "" if key == "-" else key
    updated.setdefault("enabled", True)
    if input("Test catalog before saving? [Y/n] ").strip().lower() != "n":
        test_catalog(updated)
    if input("Save these settings? [Y/n] ").strip().lower() == "n":
        return None
    return updated


def test_catalog(profile):
    try:
        models = catalog(profile)
        print(f"Catalog returned {len(models)} model(s).")
        for model in models[:8]:
            print(f"  {model}")
    except (OSError, ValueError) as error:
        print(f"Catalog test failed: {error}. Check the URL, auth method, and key.")


def manage():
    while True:
        providers = load(CONFIG)
        name = choose("Manage providers", [("Add provider", "")] + [
            (name + ("" if profile["enabled"] else " (disabled)"), name)
            for name, profile in sorted(providers.items())
        ], searchable=True)
        if name is None:
            return
        try:
            if not name:
                name = input("Provider name (letters, numbers, hyphens): ").strip().lower()
                if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name) or name in providers or name == "native":
                    raise ValueError("Choose a unique provider name using letters, digits, or hyphens.")
                updated = edit({})
                if updated is None:
                    continue
                providers[name] = updated
            else:
                profile = providers[name]
                action = choose(name, [(item, item) for item in (
                    "Edit", "Test catalog", "Disable" if profile["enabled"] else "Enable", "Delete"
                )])
                if action == "Test catalog":
                    test_catalog(profile)
                    continue
                if action == "Edit":
                    updated = edit(profile)
                    if updated is None:
                        continue
                    providers[name] = updated
                elif action in ("Enable", "Disable"):
                    profile["enabled"] = action == "Enable"
                elif action == "Delete" and input(f"Type {name} to delete it: ") == name:
                    del providers[name]
                else:
                    continue
            save(CONFIG, providers)
            cached = load(CACHE)
            if name in cached:
                del cached[name]
                save(CACHE, cached)
            print("Provider settings saved.")
        except (OSError, ValueError) as error:
            print(f"Could not save provider: {error}")


def select_model(harness, providers):
    options = [(f"Native {harness} — open with your normal account and model picker", ("native", None))]
    if harness == "claude":
        options.extend((f"{model.title()} — native Claude Code", ("native", model))
                       for model in ("opus", "sonnet", "haiku"))
    cache = load(CACHE)
    for name, profile in providers.items():
        if not profile["enabled"] or not profile[harness]:
            continue
        try:
            live = catalog(profile)
            cache[name] = live
            status = ""
        except (OSError, ValueError) as error:
            live = cache.get(name, [])
            status = " (cached)"
            print(f"{name}: catalog unavailable ({error}). Check settings in Manage providers.", file=sys.stderr)
        for model in sorted(set(profile["manual"]) | set(live)):
            options.append((f"{model} — {name}" + (status if model not in profile["manual"] else ""), (name, model)))
        options.append((f"Enter a model ID — {name}", (name, None)))
    if cache:
        save(CACHE, cache)
    return choose(f"Select a model for {harness}", options, searchable=True)


def launch(harness, name, model, providers, passthrough):
    env = os.environ.copy()
    args = [COMMANDS[harness]]
    if name != "native":
        profile = providers.get(name)
        if not profile or not profile["enabled"] or not profile[harness]:
            raise ValueError(f"Provider {name!r} has no enabled {harness} route.")
        base = profile["base"] if profile[harness] == "=" else profile[harness]
        if not model:
            raise ValueError("Supply a model ID with --model.")
        if harness == "claude":
            env["CLAUDE_CONFIG_DIR"] = str(ROOT / "claude" / name)
            env["ANTHROPIC_BASE_URL"] = base.rstrip("/")
            env.pop("ANTHROPIC_API_KEY", None)
            env.pop("ANTHROPIC_AUTH_TOKEN", None)
            if profile["key"]:
                key_var = "ANTHROPIC_AUTH_TOKEN" if profile["claude_auth"] == "bearer" else "ANTHROPIC_API_KEY"
                env[key_var] = profile["key"]
            for var in ("MODEL", "DEFAULT_OPUS_MODEL", "DEFAULT_SONNET_MODEL", "DEFAULT_HAIKU_MODEL", "SMALL_FAST_MODEL"):
                env[f"ANTHROPIC_{var}"] = model
        else:
            env["CODEX_HOME"] = str(ROOT / "codex" / name)
            Path(env["CODEX_HOME"]).mkdir(parents=True, exist_ok=True, mode=0o700)
            args.extend(["-c", 'model_provider="picker"', "-c", 'model_providers.picker.name="Provider Picker"',
                         "-c", f"model_providers.picker.base_url={json.dumps(base.rstrip('/'), ensure_ascii=False)}",
                         "-c", 'model_providers.picker.wire_api="responses"'])
            if profile["key"]:
                env["PROVIDER_PICKER_API_KEY"] = profile["key"]
                args.extend(["-c", 'model_providers.picker.env_key="PROVIDER_PICKER_API_KEY"'])
    if model:
        args.extend(["--model", model])
    os.execvpe(args[0], args + passthrough, env)


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog="Run without arguments for the menu. Put harness arguments after --.")
    parser.add_argument("mode", nargs="?", choices=(*COMMANDS, "providers", "help"))
    parser.add_argument("--provider", help="Saved provider name, or native")
    parser.add_argument("--model", help="Exact model ID to launch")
    cli, separator, passthrough = sys.argv[1:], "--", []
    if separator in cli:
        delimiter = cli.index(separator)
        cli, passthrough = cli[:delimiter], cli[delimiter + 1:]
    args = parser.parse_args(cli)
    try:
        mode = args.mode
        if not mode:
            mode = choose("Provider Picker", [
                ("Launch Claude Code", "claude"), ("Launch Codex", "codex"),
                ("Manage providers", "providers"), ("Help", "help"),
            ])
        if mode == "help":
            parser.print_help()
        elif mode == "providers":
            manage()
        elif mode:
            providers = load(CONFIG)
            if args.provider or args.model:
                selection = (args.provider or "native", args.model)
            else:
                selection = select_model(mode, providers)
                if selection and selection[0] != "native" and selection[1] is None:
                    selection = (selection[0], input("Exact model ID: ").strip())
            if selection:
                launch(mode, *selection, providers, passthrough)
    except (KeyboardInterrupt, EOFError):
        return 130
    except (OSError, ValueError) as error:
        print(f"provider-picker: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
