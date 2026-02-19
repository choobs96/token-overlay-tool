#!/bin/bash
# Token Overlay - One-Command Installer (Cross-Platform)
# Usage: curl -sSL <URL>/install.sh | bash -s -- --api-key "KEY" --email "EMAIL"
set -e

# Parse command-line arguments
API_KEY=""
EMAIL=""
DATASET="claude-code"
ENVIRONMENT=""
REPO_URL="${REPO_URL:-https://raw.githubusercontent.com/choobs96/token-overlay-tool/main}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --api-key) API_KEY="$2"; shift 2 ;;
        --email) EMAIL="$2"; shift 2 ;;
        --dataset) DATASET="$2"; shift 2 ;;
        --environment) ENVIRONMENT="$2"; shift 2 ;;
        --repo) REPO_URL="$2"; shift 2 ;;
        *) shift ;;
    esac
done

# Prompt if not provided
if [ -z "$API_KEY" ]; then
    read -p "Enter Honeycomb API Key: " API_KEY
fi
if [ -z "$EMAIL" ]; then
    read -p "Enter your email: " EMAIL
fi
if [ -z "$ENVIRONMENT" ]; then
    read -p "Enter Honeycomb environment: " ENVIRONMENT
fi

echo "🚀 Installing Token Overlay..."

# Detect OS and shell
OS="$(uname -s)"
SHELL_RC=""

case "$OS" in
    Darwin)
        SHELL_RC="$HOME/.zshrc"
        ;;
    Linux)
        # Try to detect shell
        if [ -n "$ZSH_VERSION" ]; then
            SHELL_RC="$HOME/.zshrc"
        else
            SHELL_RC="$HOME/.bashrc"
        fi
        ;;
    MINGW*|MSYS*|CYGWIN*)
        echo "❌ Windows not yet supported (use WSL2 or Linux)"
        exit 1
        ;;
    *)
        echo "❌ Unsupported OS: $OS"
        exit 1
        ;;
esac

# Create install directory
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"

# Get the script (local if available, otherwise download)
INSTALL_PATH="$INSTALL_DIR/token-overlay"

# Check if token-overlay.py exists in current directory (running from unzipped folder)
if [ -f "./token-overlay.py" ]; then
    echo "📥 Installing from local token-overlay.py..."
    cp ./token-overlay.py "$INSTALL_PATH"
else
    if [ -n "$REPO_URL" ]; then
        echo "📥 Downloading Token Overlay..."
        SCRIPT_URL="$REPO_URL/token-overlay.py"
        if command -v curl > /dev/null; then
            curl -sSL "$SCRIPT_URL" -o "$INSTALL_PATH"
        elif command -v wget > /dev/null; then
            wget -q "$SCRIPT_URL" -O "$INSTALL_PATH"
        else
            echo "❌ Neither curl nor wget found."
            exit 1
        fi
    else
        echo "❌ token-overlay.py not found in current directory. Run install.sh from the unzipped folder."
        exit 1
    fi
fi

chmod +x "$INSTALL_PATH"
echo "✅ Installed Token Overlay"

# Create config directory and file
echo "📝 Creating configuration..."
mkdir -p "$HOME/.config/token-overlay"
CONFIG_FILE="$HOME/.config/token-overlay/config.json"

cat > "$CONFIG_FILE" <<EOF
{
  "api_key": "$API_KEY",
  "user_email": "$EMAIL",
  "dataset": "$DATASET",
  "environment": "$ENVIRONMENT"
}
EOF

chmod 600 "$CONFIG_FILE"
echo "✅ Created config at $CONFIG_FILE"

# Add auto-start function to shell config (if not already present)
echo "🔧 Setting up auto-start..."
if [ -f "$SHELL_RC" ]; then
    if ! grep -q "_start_token_overlay" "$SHELL_RC" 2>/dev/null; then
        cat >> "$SHELL_RC" <<'SHELLRC'

# Token Overlay Auto-Start
_start_token_overlay() {
    [ ! -f "$HOME/.config/token-overlay/config.json" ] && return
    if [ -f "$HOME/.config/token-overlay/.pid" ]; then
        pid=$(cat "$HOME/.config/token-overlay/.pid" 2>/dev/null)
        ps -p "$pid" > /dev/null 2>&1 && return
    fi
    nohup "$HOME/.local/bin/token-overlay" > /dev/null 2>&1 &
}

# Hook for zsh
if [ -n "$ZSH_VERSION" ]; then
    if [ -z "$(declare -f preexec)" ]; then
        preexec() { case "$1" in claude*) _start_token_overlay ;; esac }
    fi
fi

# Hook for bash (using DEBUG trap)
if [ -n "$BASH_VERSION" ]; then
    trap '_cmd="$BASH_COMMAND"; case "$_cmd" in claude*) _start_token_overlay ;; esac' DEBUG
fi
SHELLRC
        echo "✅ Added auto-start function to $SHELL_RC"
    else
        echo "✅ Auto-start function already present in $SHELL_RC"
    fi
else
    echo "⚠️  Shell config not found: $SHELL_RC"
fi

# Start overlay now
echo "🎬 Starting overlay..."
nohup "$INSTALL_PATH" > /dev/null 2>&1 &

echo ""
echo "🎉 Installation complete!"
echo ""
echo "✨ Next time you run 'claude', the overlay will auto-start."
echo ""
echo "📝 Config location: ~/.config/token-overlay/config.json"
echo "🔄 To update config: Edit the JSON file or re-run install.sh"
echo "❌ To uninstall: rm ~/.local/bin/token-overlay && rm -rf ~/.config/token-overlay"
echo ""
