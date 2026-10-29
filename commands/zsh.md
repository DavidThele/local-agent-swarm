# Command: Zsh

**Description:**
Executes a terminal command in the local environment. Subject to the system security protocol (whitelisted commands execute silently; greylisted/blacklisted commands pause and request explicit user approval).

**Attributes:**
- `timeout` (optional): Maximum execution time in seconds before killing the process. Default is 30.

**Child Tags:**
- `<Command>`: The exact shell command string to execute.

**Example Usage:**
<Zsh timeout="15">
    <Command>grep -rnw '/Users/davidthele/Documents/project/' -e 'TODO'</Command>
</Zsh>