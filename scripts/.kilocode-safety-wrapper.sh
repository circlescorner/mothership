#!/bin/bash
# Safety wrapper for Kilo Code terminal commands
# Prevents interactive prompts from hanging the terminal

# Set non-interactive mode
export DEBIAN_FRONTEND=noninteractive
export APT_LISTCHANGES_FRONTEND=none

# Add timeouts to all network operations
alias curl='curl --max-time 30 --connect-timeout 10'
alias wget='wget --timeout=30 --tries=3'

# SSH with strict timeouts
alias ssh='ssh -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=3'

# Run commands with automatic timeout protection
timeout_safe() {
    local duration="$1"
    shift
    timeout --signal=TERM --kill-after=5 "$duration" "$@"
}

# Example usage in your scripts:
# timeout_safe 300 apt-get update  # 5 minute max
# timeout_safe 600 apt-get upgrade -y  # 10 minute max
