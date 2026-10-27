-- Dreamcatcher (SessionView.app): one click on the dock opens sessionview
-- (the tmux sidebar) in WHATEVER TERMINAL THE USER PREFERS.
--
-- It was cut from an app wired to one terminal (Ghostty). The terminal is the
-- user's choice, whatever that is, never one this app picks for them.
--
-- An earlier version hard-wired "$HOME/Code/sessionview/bin/sessionview" to
-- make the path portable, and on a machine whose clone lived elsewhere the dock
-- icon did nothing from a cold start. A missing path failed SILENTLY -- the
-- terminal opened, printed one line and closed, so the user could not tell
-- that it had failed, or why.
--
-- So the launcher no longer contains a path at all. It ASKS the login shell
-- where sessionview is, exactly as a human would, and when the answer is
-- nothing it SAYS SO IN A DIALOG instead of flashing a window.
--
-- How the terminal is chosen: see chooseTerminal() below (macOS has no
-- system-wide "default terminal" setting, so it asks sessionview's resolver).
--
-- The command runs in the user's LOGIN, interactive shell (userShell()): that
-- shell's profile is where PATH is defined, so it is what finds tmux and
-- sessionview. A login shell may be zsh or a Homebrew bash.
--
-- tmux does NOT need to be running first. sessionview-frame lands in a
-- session tmux already has, and creates one (main) when there is none
-- ("has-session ... || new-session -d"), so a cold boot is a supported
-- start. What it cannot survive is tmux not being INSTALLED, which is why
-- that is checked and named below.

set sv to resolveLauncher()
set cmd to (quoted form of userShell()) & " -lic " & quoted form of (quoted form of sv)
set term to chooseTerminal()
set wantFull to wantsFullscreen()

if term is "iterm" then
	-- iTerm's words (`create window ...`, `fullscreen`) come from iTerm's own
	-- dictionary, and AppleScript looks a dictionary up when the script is
	-- COMPILED, not when it runs. Written as a plain tell block they made this
	-- whole file fail to compile on a Mac without iTerm, so the Dock app could
	-- not be built there at all, even for a user who never picks iTerm.
	--
	-- So the iTerm block is a STRING, compiled only when this branch runs, and
	-- only then needs iTerm. It is the same statements, run by `run script` in
	-- this same process, so the Automation consent the user gave this app for
	-- iTerm still applies. cmd and wantFull go in as PARAMETERS, never spliced
	-- into the text, so no quote in a path can break it.
	set itermScript to "on run {cmd, wantFull}
	tell application \"iTerm\"
		activate
		create window with default profile command cmd
		if wantFull then
			try
				set fullscreen of current window to true
			end try
		end if
	end tell
end run"
	try
		run script itermScript with parameters {cmd, wantFull}
	on error errMsg number errNum
		if errNum is -128 then error number -128
		-- e.g. `terminal: iterm` in the config on a Mac where iTerm is not
		-- installed: the string does not compile here. Say so; never fail mute.
		display alert "SessionView cannot open iTerm" message "iTerm is the terminal chosen for sessionview, but it could not be run:
" & errMsg & " (" & errNum & ")

Is iTerm installed? Install it, or choose another terminal:  sessionview config set terminal terminal" as critical
		error number -128
	end try
else if term is "ghostty" then
	set ghosttyArgs to "--working-directory=$HOME"
	if wantFull then set ghosttyArgs to ghosttyArgs & " --fullscreen=true"
	do shell script "/usr/bin/open -na Ghostty.app --args " & ghosttyArgs & " --initial-command=" & quoted form of cmd
else
	-- ONE WINDOW ON A COLD CLICK.
	--
	-- Terminal opens a window FOR ITSELF the moment it launches ("Startup
	-- Window Settings" in its prefs). So on a cold click `activate` gives us
	-- a window we did not ask for, and `do script` then asks for a second:
	-- two windows, every time, from a quit Terminal (measured and reproduced:
	-- quit, one click, two windows).
	--
	-- So when Terminal was NOT already running, we use the window it just
	-- handed us instead of asking for another -- but only while that window
	-- is IDLE. If the user's profile runs a command of its own, that window
	-- is busy and typing into it would interleave with whatever it is doing,
	-- so we open our own and accept the spare. Warm clicks are unchanged:
	-- no startup window is created, so we always ask for one.
	set wasRunning to isRunning("Terminal")
	tell application "Terminal"
		activate
		if wasRunning then
			do script cmd
		else
			set reused to false
			-- the startup window appears asynchronously; wait, briefly
			repeat 40 times
				if (count of windows) > 0 then exit repeat
				delay 0.1
			end repeat
			-- and it reports BUSY for about a second while login and the
			-- shell start (measured: 1.1 s, true -> false).
			-- Checking once, immediately, always saw busy and always opened
			-- a second window - the bug this whole branch exists to avoid.
			repeat 30 times
				try
					if not (busy of selected tab of front window) then exit repeat
				end try
				delay 0.1
			end repeat
			try
				if not (busy of selected tab of front window) then
					do script cmd in front window
					set reused to true
				end if
			end try
			if not reused then do script cmd
		end if
	end tell
	if wantFull then fullscreenTerminal()
end if

-- Where is sessionview? Ask the login shell first (that is what "installed"
-- means for a CLI), then the two repo layouts we know, then give up LOUDLY.
on resolveLauncher()
	-- 1. the user's own login shell (zsh on a stock Mac, with PATH from its
	--    rc files), exactly as a new terminal window would find it
	try
		set p to inShell("command -v sessionview")
		if p starts with "/" then return p
	end try
	-- 2. where the installers put it: uv tool, Homebrew, a clone
	repeat with candidate in {"$HOME/.local/bin/sessionview", "/opt/homebrew/bin/sessionview", "/usr/local/bin/sessionview", "$HOME/Code/sessionview/bin/sessionview"}
		try
			return do shell script "p=" & quoted form of (contents of candidate) & "; p=$(eval printf %s \"$p\"); test -x \"$p\" && printf %s \"$p\""
		end try
	end repeat
	set extra to ""
	try
		set t to inShell("command -v tmux")
		if t does not start with "/" then error "no tmux"
	on error
		set extra to "
tmux is not installed either. Install it first:  brew install tmux"
	end try
	display alert "SessionView cannot start" message "sessionview was not found." & "
Looked for it on your PATH (your login shell), then in ~/.local/bin, /opt/homebrew/bin, /usr/local/bin and ~/Code/sessionview.
Install it:  uv tool install sessionview" & extra as critical
	error number -128
end resolveLauncher

-- The user's login shell, from the directory service (zsh on a stock Mac).
on userShell()
	try
		set sh to do shell script "dscl . -read ~ UserShell | sed 's/^UserShell: //'"
		if sh starts with "/" then return sh
	end try
	return "/bin/zsh"
end userShell

-- Run CMD in the user's login, interactive shell: the PATH a new terminal
-- window has. Interactive rc files may print, so keep the last line only.
on inShell(cmd)
	return do shell script (quoted form of userShell()) & " -lic " & (quoted form of cmd) & " 2>/dev/null | tail -n 1"
end inShell

-- THE ANSWER COMES FROM sessionview-terminal, which
-- reads the same three-layer config cascade as everything else in sessionview:
-- `terminal` in the config, then a terminal running now, then iTerm, then
-- Terminal. There is no one-word sidecar file (~/.config/sessionview/terminal):
-- a second config system would be invisible to `sessionview-config dump`.
--
-- Why this applet no longer decides: the old fallback order picked whatever
-- was RUNNING, so a click worked while a terminal happened to be open and
-- chose iTerm after a reboot, when nothing was. After a reboot, one click
-- must open the user's PREFERRED terminal, and that order failed it.
--
-- The local rules below stay as a LAST resort, because a missing resolver must
-- never cost the user the click.
on chooseTerminal()
	-- 1. the resolver: `sessionview terminal`, beside the sessionview we found
	try
		set t to inShell(quoted form of resolveLauncher() & " terminal")
		if t is in {"iterm", "ghostty", "terminal"} then return t
	end try
	-- 2. no resolver: the applet's own last resort
	if isRunning("iTerm2") then return "iterm"
	if isRunning("Terminal") then return "terminal"
	if isRunning("ghostty") then return "ghostty"
	if isInstalled("iTerm") then return "iterm"
	return "terminal"
end chooseTerminal

-- FULL SCREEN, as a configurable choice. The switch is the ONE config
-- cascade, like everything else: `fullscreen` in ~/.sessionkit/view/settings/view.json,
-- default false. No sidecar file, no second config system.
on wantsFullscreen()
	try
		set v to inShell(quoted form of resolveLauncher() & " config get fullscreen")
		return v is "true"
	end try
	return false
end wantsFullscreen

-- Terminal.app has no scriptable full screen (`zoomed` is MAXIMISE, a
-- different thing), so this goes through the accessibility API, which needs
-- permission the first time. A silent no-op here would leave the user unable
-- to tell why it failed, so a refusal SAYS SO and names the pane to tick.
on fullscreenTerminal()
	delay 0.3
	try
		tell application "System Events" to tell process "Terminal"
			set frontmost to true
			set value of attribute "AXFullScreen" of front window to true
		end tell
	on error errMsg number errNum
		if errNum is -1719 or errNum is -25211 or errNum is -1728 then
			display alert "SessionView cannot go full screen" message "macOS has not given this app permission to control windows.

System Settings > Privacy & Security > Accessibility > turn ON SessionView (add it with + if it is not listed), then click the icon again.

Everything else worked - your terminal is open behind this dialog." as warning
		end if
	end try
end fullscreenTerminal

on isRunning(procName)
	try
		do shell script "/usr/bin/pgrep -x " & quoted form of procName & " >/dev/null"
		return true
	on error
		return false
	end try
end isRunning

on isInstalled(appName)
	try
		do shell script "test -d /Applications/" & appName & ".app || test -d \"$HOME/Applications/" & appName & ".app\""
		return true
	on error
		return false
	end try
end isInstalled

