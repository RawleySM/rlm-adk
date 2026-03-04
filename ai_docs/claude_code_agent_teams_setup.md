# Claude Code Agent Teams & Tmux Setup

This document records the setup process for enabling and optimizing **Claude Code Agent Teams** with terminal splitting on Linux Ubuntu.

## 1. Overview
Claude Code Agent Teams (introduced Feb 2026) allow multiple independent Claude instances to coordinate on tasks. To see teammates working simultaneously, a "split-pane" mode is supported via **tmux**.

## 2. Prerequisites
The following packages were installed using `apt`:
- `tmux`: Terminal multiplexer for split-pane support.
- `git`: Required for installing the Tmux Plugin Manager (TPM).

```bash
sudo apt update && sudo apt install tmux git -y
```

## 3. Configuration

### Claude Code Settings
Agent Teams are enabled in `~/.claude/settings.json` via the experimental flag:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

### Tmux Configuration (`~/.tmux.conf`)
A custom configuration was created to improve ergonomics and support mouse interaction (allowing you to click into teammate panes):

```tmux
# --- GENERAL ---
set -g default-terminal "screen-256color"
set -g mouse on               # Critical for clicking teammate panes
set -g base-index 1           # Start numbering at 1
setw -g pane-base-index 1

# --- ERGONOMICS ---
unbind C-b
set -g prefix C-a             # Use Ctrl-a (easier reach)
bind C-a send-prefix

# Intuitive splits
bind | split-window -h -c "#{pane_current_path}"
bind - split-window -v -c "#{pane_current_path}"

# Vim-style pane switching (h, j, k, l)
bind h select-pane -L
bind j select-pane -D
bind k select-pane -U
bind l select-pane -R

# --- PLUGINS ---
set -g @plugin 'tmux-plugins/tpm'
set -g @plugin 'tmux-plugins/tmux-sensible'
set -g @plugin 'tmux-plugins/tmux-resurrect'   # Save sessions
set -g @plugin 'tmux-plugins/tmux-continuum'   # Auto-save
set -g @plugin 'catppuccin/tmux'               # Modern theme

run '~/.tmux/plugins/tpm/tpm'
```

### Tmux Plugin Manager (TPM)
TPM was installed to `~/.tmux/plugins/tpm`:
```bash
git clone https://github.com/tmux-plugins/tpm ~/.tmux/plugins/tpm
```

## 4. Usage

### Activating the Setup
1. **Start Tmux**: `tmux new -s agent-team`
2. **Install Plugins**: Inside tmux, press `Ctrl-a` then `Shift-i`.
3. **Launch Claude**: `claude --teammate-mode tmux`

### Coordinate a Team
Once inside Claude, trigger a team using natural language:
> "Create an agent team to help me review the rlm-adk project architecture."

### Navigation
- **Switch Panes**: Use the mouse to click or `Ctrl-a` + `h/j/k/l`.
- **Cycle Teammates (In-process)**: `Shift+Up` / `Shift+Down`.
- **Shutdown Team**: Say "Shut down the team" or "Wrap it up".
