"""Terminal launcher for Claude Code and Codex."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import shlex
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
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
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
    prefix = profile.get("catalog_prefix", "")
    return sorted({model for model in models if isinstance(model, str) and model.isprintable()
                   and model.strip() and model.startswith(prefix)})


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


def edit_advanced(profile):
    updated = dict(profile)
    print("Press Enter to keep a value, or type - to clear an optional field.")
    updated["base"] = checked_url(prompt("Base URL", profile.get("base", ""),
                                         "Use the API base URL supplied by your provider."))
    updated["catalog_url"] = prompt("Catalog URL", profile.get("catalog_url", ""),
                                    "Optional. Leave blank to derive the models URL from the base URL.")
    if updated["catalog_url"]:
        checked_url(updated["catalog_url"])
    updated["catalog_prefix"] = prompt("Catalog model ID prefix", profile.get("catalog_prefix", ""),
                                       "Optional. Show only live model IDs beginning with this prefix.")
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
    updated["default_model"] = prompt("Default model ID", profile.get("default_model", ""),
                                      "Optional. Used when launching with --provider and no --model.")
    updated["small_model"] = prompt("Claude background model", profile.get("small_model", ""),
                                    "Optional. Leave blank to use the selected model.")
    key_status = "configured" if profile.get("key") else "empty"
    key = getpass.getpass(f"API key ({key_status}; Enter to keep, - to clear): ")
    updated["key"] = profile.get("key", "") if not key else "" if key == "-" else key
    updated.setdefault("enabled", True)
    if input("Test catalog before saving? [Y/n] ").strip().lower() != "n":
        test_catalog(updated)
    if input("Save these settings? [Y/n] ").strip().lower() == "n":
        return None
    return updated


def edit(profile):
    base = checked_url(prompt("Base URL", profile.get("base", ""),
                              "Use the API base URL shown in your provider's documentation.")).rstrip("/")
    status = "configured; Enter to keep" if profile.get("key") else "leave blank for a local endpoint without auth"
    key = getpass.getpass(f"API key ({status}): ")
    updated = {
        "base": base, "key": profile.get("key", "") if not key else "" if key == "-" else key,
        "enabled": profile.get("enabled", True), "manual": profile.get("manual", []),
        "default_model": profile.get("default_model", ""), "small_model": profile.get("small_model", ""),
        "catalog_prefix": profile.get("catalog_prefix", ""),
    }
    if profile and not profile.get("auto_catalog"):
        updated = profile | updated
    else:
        root = base.removesuffix("/v1")
        versioned = root + "/v1"
        updated.update(claude=root, codex=versioned, claude_auth="key",
                       catalog_url="", catalog_auth="bearer", auto_catalog=True)
    test_catalog(updated)
    return updated


def read_catalog(profile):
    if not profile.get("auto_catalog"):
        return catalog(profile)
    base = profile["base"]
    endpoints = dict.fromkeys((base + "/models", base.removesuffix("/v1") + "/v1/models"))
    first_error = None
    succeeded = False
    for url in endpoints:
        for method in ("bearer", "anthropic"):
            try:
                models = catalog(profile | {"catalog_url": url, "catalog_auth": method})
                succeeded = True
                if models:
                    return models
            except (OSError, ValueError) as error:
                if first_error is None:
                    first_error = error
    if first_error and not succeeded:
        raise first_error
    return []


def test_catalog(profile):
    try:
        models = read_catalog(profile)
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
                    "Edit URL or key", "Advanced settings", "Test catalog", "Disable" if profile["enabled"] else "Enable", "Delete"
                )])
                if action == "Test catalog":
                    test_catalog(profile)
                    continue
                if action in ("Edit URL or key", "Advanced settings"):
                    if action == "Advanced settings":
                        updated = edit_advanced(profile | {"advanced": True, "auto_catalog": False})
                    else:
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


def select_provider(harness, providers):
    options = [(f"Native {harness} — use your normal account", "native")]
    options.extend((name, name) for name, profile in providers.items()
                   if profile["enabled"] and profile[harness])
    return choose(f"Select a provider for {harness} (choose models in /model)", options, searchable=True)


def provider_models(name, profile):
    cache = load(CACHE)
    try:
        live = read_catalog(profile)
        if live:
            cache[name] = live
            save(CACHE, cache)
    except (OSError, ValueError) as error:
        live = cache.get(name, [])
        fallback = " Using last successful catalog." if live else ""
        print(f"{name}: catalog unavailable ({error}).{fallback}", file=sys.stderr)
    return sorted(set(live) | set(profile["manual"]))


def codex_catalog(name, models):
    rows = []
    for priority, model in enumerate(models):
        rows.append(dict(
            slug=model, display_name=model, description=f"Served by {name}", priority=priority,
            shell_type="shell_command", visibility="list", supported_in_api=True,
            default_reasoning_level=None, supported_reasoning_levels=[],
            base_instructions="You are a coding assistant. Work with the user to complete their task.",
            supports_reasoning_summaries=False, support_verbosity=False,
            apply_patch_tool_type="freeform", truncation_policy={"mode": "bytes", "limit": 10000},
            supports_parallel_tool_calls=False,
        ))
    path = ROOT / "codex" / name / "catalog.json"
    save(path, {"models": rows})
    return path


def launch(harness, name, model, providers, passthrough):
    env = os.environ.copy()
    args = [COMMANDS[harness]]
    if name != "native":
        profile = providers.get(name)
        if not profile or not profile["enabled"] or not profile[harness]:
            raise ValueError(f"Provider {name!r} has no enabled {harness} route.")
        base = profile["base"] if profile[harness] == "=" else profile[harness]
        models = provider_models(name, profile)
        model = model or profile.get("default_model") or next(iter(models), None)
        if not model:
            raise ValueError("No models found. Check the provider catalog or supply --model MODEL_ID.")
        models = sorted(set(models) | {model})
        if harness == "claude":
            env["CLAUDE_CONFIG_DIR"] = str(ROOT / "claude" / name)
            env["ANTHROPIC_BASE_URL"] = base.rstrip("/")
            settings = Path(env["CLAUDE_CONFIG_DIR"]) / "provider-picker-settings.json"
            save(settings, {"modelPicker": {
                "replaceBuiltInOptions": True,
                "options": [{"model": item, "label": item, "description": f"Served by {name}"}
                            for item in models],
            }})
            args.extend(["--settings", str(settings)])
            env.pop("ANTHROPIC_API_KEY", None)
            env.pop("ANTHROPIC_AUTH_TOKEN", None)
            if profile["key"]:
                key_var = "ANTHROPIC_AUTH_TOKEN" if profile["claude_auth"] == "bearer" else "ANTHROPIC_API_KEY"
                env[key_var] = profile["key"]
            for var in ("MODEL", "DEFAULT_OPUS_MODEL", "DEFAULT_SONNET_MODEL", "DEFAULT_HAIKU_MODEL", "SMALL_FAST_MODEL"):
                env[f"ANTHROPIC_{var}"] = model
            if profile.get("small_model"):
                env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = profile["small_model"]
                env["ANTHROPIC_SMALL_FAST_MODEL"] = profile["small_model"]
        else:
            env["CODEX_HOME"] = str(ROOT / "codex" / name)
            path = codex_catalog(name, models)
            args.extend(["-c", f"model_catalog_json={json.dumps(str(path), ensure_ascii=False)}"])
            args.extend(["-c", 'model_provider="picker"', "-c", 'model_providers.picker.name="Provider Picker"',
                         "-c", f"model_providers.picker.base_url={json.dumps(base.rstrip('/'), ensure_ascii=False)}",
                         "-c", 'model_providers.picker.wire_api="responses"'])
            if profile["key"]:
                env["PROVIDER_PICKER_API_KEY"] = profile["key"]
                args.extend(["-c", 'model_providers.picker.env_key="PROVIDER_PICKER_API_KEY"'])
    if model:
        args.extend(["--model", model])
    os.execvpe(args[0], args + passthrough, env)


def import_local_claude(directory):
    paths = sorted((*directory.glob("*.env"), *directory.glob("*.env.disabled")))
    if not paths:
        raise ValueError("No .env or .env.disabled profiles found in the specified directory.")
    providers = load(CONFIG)
    imports = {}
    for path in paths:
        stem = path.name.removesuffix(".disabled").removesuffix(".env")
        name = re.sub(r"^\d{2}-", "", stem)
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name) or name == "native":
            raise ValueError(f"Unsupported provider name in {path.name}.")
        if name in providers or name in imports:
            raise ValueError(f"Provider {name!r} already exists. Import stopped without changes.")
        values = {}
        for number, line in enumerate(path.read_text().splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                tokens = shlex.split(stripped, comments=True)
                if tokens and tokens[0] == "export":
                    tokens.pop(0)
                if len(tokens) != 1 or not re.fullmatch(r"ALT_[A-Z_]+=.*", tokens[0]):
                    raise ValueError
                key, value = tokens[0].split("=", 1)
                values[key] = value
            except ValueError:
                raise ValueError(f"Unsupported assignment in {path.name}, line {number}.") from None
        base = checked_url(values.get("ALT_BASE_URL", ""))
        catalog_url = values.get("ALT_MODELS_URL", "")
        if catalog_url:
            checked_url(catalog_url)
        imports[name] = {
            "base": base,
            "catalog_url": catalog_url,
            "catalog_auth": "bearer",
            "catalog_prefix": values.get("ALT_MODELS_PREFIX", ""),
            "claude": "=",
            "claude_auth": "bearer" if values.get("ALT_AUTH_STYLE") == "bearer" else "key",
            "codex": "",
            "default_model": values.get("ALT_MODEL", ""),
            "small_model": values.get("ALT_SMALL_MODEL", ""),
            "key": values.get("ALT_API_KEY", ""),
            "manual": re.split(r"[\s,]+", values.get("ALT_MODELS", "").strip()) if values.get("ALT_MODELS", "").strip() else [],
            "enabled": not path.name.endswith(".disabled"),
        }
    save(CONFIG, providers | imports)
    print("Imported providers: " + ", ".join(imports))


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog="Run without arguments for the menu. Put harness arguments after --.")
    parser.add_argument("mode", nargs="?", choices=(*COMMANDS, "providers", "import-local-claude", "help"))
    parser.add_argument("--directory", type=Path, help="Legacy provider directory for import-local-claude")
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
        elif mode == "import-local-claude":
            import_local_claude(args.directory or Path.home() / ".claude-local" / "providers")
        elif mode:
            providers = load(CONFIG)
            if args.provider or args.model:
                selection = (args.provider or "native", args.model)
            else:
                name = select_provider(mode, providers)
                selection = (name, None) if name is not None else None
            if selection:
                launch(mode, *selection, providers, passthrough)
    except (KeyboardInterrupt, EOFError):
        return 130
    except (OSError, ValueError) as error:
        print(f"provider-picker: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
