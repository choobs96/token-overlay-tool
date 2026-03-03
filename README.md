# Token Overlay - Claude Code Usage Monitor

A floating desktop widget that shows your Claude Code token usage from Honeycomb.

## Prerequisites

- Python 3.10+
- A Honeycomb API key with read access to your Claude Code dataset
- Your email address (used to filter usage data)

## Install

### Option A: From zip

Download `token-overlay-tool.zip` from this repo, then:

```bash
unzip token-overlay-tool.zip
cd token-overlay-tool
bash install.sh --api-key "YOUR_HONEYCOMB_API_KEY" --email "your.email@company.com"
```

### Option B: From repo

```bash
git clone https://github.com/choobs96/token-overlay-tool.git
cd token-overlay-tool
bash install.sh --api-key "YOUR_HONEYCOMB_API_KEY" --email "your.email@company.com"
```

The installer will prompt for any missing values. It also sets up auto-start so the overlay launches whenever you run `claude`.

## Usage

```bash
~/.local/bin/token-overlay         # Standard view
~/.local/bin/token-overlay --mini  # Compact view
```

### Views

- **Overall** - 7-day totals with model breakdown
- **Daily** - Per-day token and cost breakdown
- **30min** - Last 30 minutes of usage

### Theme & Transparency

- **Dark/Light theme** - Toggle via the `☾`/`☀` button in Settings
- **Transparency** - Adjust window opacity (0.3–1.0) with the slider in Settings; changes preview live and persist across restarts

### Updating

The overlay checks for updates on startup. If a new version is available, the Settings icon (`⚙`) turns orange. Open Settings and click the download button (`⇣`) to install the latest version.

### Configuration

Config is stored at `~/.config/token-overlay/config.json`:

```json
{
  "api_key": "your-honeycomb-api-key",
  "user_email": "your.email@company.com",
  "dataset": "claude-code",
  "environment": "your-environment",
  "theme": "dark",
  "opacity": 1.0
}
```

You can also edit settings from the overlay UI via the Settings button (`⚙`).

## Uninstall

```bash
rm ~/.local/bin/token-overlay
rm -rf ~/.config/token-overlay
```

Then remove the "Token Overlay Auto-Start" section from your `~/.zshrc` or `~/.bashrc`.
