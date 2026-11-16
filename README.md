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
2. Enter the provider's API base and key. For an OpenAI-style base ending in `/v1`, the default catalog is `<base>/models` with bearer authentication. Supply a catalog URL if the provider uses another endpoint. For an Anthropic catalog, select `anthropic` authentication.
3. Fill in the API base for each supported harness. Enter `=` to reuse the provider base, or leave the route blank. Claude Code needs Anthropic Messages. Codex needs OpenAI Responses. Use the base documented for the client, without the final `/messages` or `/responses` segment. Claude Code normally appends `/v1/messages`; Codex appends `/responses` to its base.
4. Test the catalog, review the returned model IDs, and save. If the provider has no catalog endpoint, supply comma-separated model IDs or enter a model ID at launch.

To rotate a key or change a URL, select the provider and choose **Edit**. Press Enter to keep the displayed value or the existing key. Type `-` to clear an optional field or key. The menu also lets you test the catalog, disable a provider temporarily, or delete it.

## Launch a harness

```sh
provider-picker claude
provider-picker codex
provider-picker codex --provider my-gateway --model model-id
provider-picker claude --provider native -- --help
```

Type part of a provider or model name to search, or choose a numbered row. The native option opens the harness using its existing sign-in and model picker. Claude Code also has native Opus, Sonnet, and Haiku shortcuts. Custom routes use a separate harness home for each provider and select the requested model at startup.

A catalog hit means the API listed the model. Verify tool use and streaming in the harness before relying on a new model. To use Claude models in Codex, configure a Responses route that serves those models. To use GPT models in Claude Code, configure a Messages route that serves them. This launcher does not translate between protocols or change the harness's in-session model picker.

If catalog refresh fails, the picker uses the last successful result and labels cached rows. Check the provider URL, auth mode, and key in **Manage providers**. Redirects are rejected so credentials are never forwarded to a redirected catalog endpoint. Use the final URL instead.

## Uninstall

Run `pipx uninstall provider-picker`. The native harness commands use their original homes and settings. For a full purge, review and delete `${XDG_CONFIG_HOME:-$HOME/.config}/provider-picker`. That directory contains the local provider config, cache, API keys, and isolated harness data, including any custom-provider session history. Its config files are owner-readable and writable, and keys are stored in plaintext there. Keep the directory out of source control and backups that you share.
