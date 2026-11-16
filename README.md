# Provider Picker

Add a provider, browse its live model catalog, and launch Claude Code or Codex from the terminal.

## Install

Install Python 3.10 or newer, pipx, and whichever harness you want to use. Make sure the harness command (`claude` or `codex`) works on its own. Then run:

```sh
pipx install 'git+https://github.com/agentixsoftware/provider-picker.git'
provider-picker
```

If the command is missing after installation, run `pipx ensurepath` and reopen your terminal. Private repository access uses your existing Git credentials.

## Add or change a provider

1. Run `provider-picker` and select **Manage providers → Add provider**.
2. Enter the provider name, API base URL, and API key. Leave the key blank for a local server that needs no authentication.
3. The picker checks the standard `/models` and `/v1/models` paths using bearer or Anthropic authentication and previews the result.

To change a base URL or rotate a key, open **Manage providers → your provider → Edit → Edit URL or key**. To remove a provider, choose **Delete** on its provider screen. Press Enter to keep an existing value or key, or type `-` to clear the key. Use **Advanced settings** for a separate catalog address, manual model IDs, or providers whose Anthropic Messages and OpenAI Responses endpoints use different bases or authentication.

## Launch a harness

```sh
provider-picker claude
provider-picker codex
provider-picker codex --provider my-gateway --model model-id
provider-picker claude --provider native -- --help
```

Running `provider-picker` shows **Manage providers** first, followed by direct launch options for the harnesses on your PATH. For example, choose **Launch Claude (via Anthropic)** or **Launch Claude (via LiteLLM)** if you saved a LiteLLM provider. Press Enter at an empty menu prompt to go back. Once the harness opens, choose a model with `/model`. Run `provider-picker --help` for command-line options. Native opens the harness with its usual sign-in and models. A custom session shows the active provider's catalog. Start another session to switch providers, or configure one gateway that routes all of your models. Claude Code requires version 2.1.242 or newer for generated model-picker entries.

Claude Code needs an Anthropic Messages route. Codex needs an OpenAI Responses route. Discovering a model does not verify that the route serves it for that harness. Claude Code handles effort controls for models it recognizes. Generic catalog entries do not declare reasoning levels, so the generated Codex catalog leaves those levels unspecified.

If catalog refresh fails, the picker uses the last successful result. Check the URL and key in **Manage providers**. Redirects are rejected so credentials are never sent to a redirected catalog endpoint.

## Uninstall

Run `pipx uninstall provider-picker`. The native harness commands use their original homes and settings. For a full purge, review and delete `${XDG_CONFIG_HOME:-$HOME/.config}/provider-picker`. That directory contains the local provider config, cache, API keys, and isolated harness data, including any custom-provider session history. Its config files are owner-readable and writable, and keys are stored in plaintext there. Keep the directory out of source control and backups that you share.

## Migrate from local-claude

Run `provider-picker import-local-claude` to import the profiles from
`~/.claude-local/providers`. Pass `--directory PATH` for a different location.
The import preserves enabled and disabled entries, default and background
models, and catalog settings. It reads simple shell assignments as data and
stops if a provider name is already in use. Try a custom launch before retiring
the old launcher. Archive the old Claude profile separately if you need its
session history.
