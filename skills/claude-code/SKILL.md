---
name: claude-code
description: >-
  Reach a Claude Code agent that is running in a tmux pane: prefer durable
  mail over keystrokes, know whether it is busy or idle before you interrupt,
  and when you must type, do it the way its input accepts. Use when a user
  asks you to tell another agent something, check on it, or start one.
---

# claude-code — mail first, keys last

Another agent's pane is a conversation in progress. Keystrokes land in the
middle of it; mail waits for its next turn.

## The order of preference

1. **Mail** — `message send AGENT-OR-SESSION-ID -s SUBJECT -f FILE`
   (sessionmail; From is your seat, there is no `--from`). Durable, signed,
   read at the agent's next turn; a listening agent's pager wakes it. The
   sidebar's Message item is this.
2. **Look** — `session list` (name, status busy/idle, context %, pane);
   `session read ID` / `session recap ID` for what it last said. Reading its pane with
   `tmux-peek` is the expensive way.
3. **Type** — only when the human wants text in that input now, and the
   seat is idle: `tmux-type PANE TEXT --force` (literal text, then Enter,
   two calls - one call does not submit into Claude Code). Multiline: send
   `M-Enter` between lines. Never type into a busy seat; never send
   Ctrl-C to one you did not start.

## Start one

`session start AGENT` in the project directory (`--tmux-target SESSION` to
place its window; `-` for a plain claude). The sidebar's **Start an agent**
runs `agent_command` from config. What an agent knows at wake is its own
business - the `session` skill explains seats, letters and mail.

## Signs

- The status line at the bottom of the pane: `⏵⏵ bypass permissions on`
  and a spinner mean busy; a bare prompt means idle. `session list` says
  the same without reading the pane.
- "Switch model?" or a permission dialog in the pane = it is waiting for a
  HUMAN; do not answer for them.
