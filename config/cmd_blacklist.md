# Command Blacklist

This file contains shell operators and characters that represent injection risks (e.g., pipes, redirects, backgrounding, subshells). If an agent attempts to use any of these, the command execution is paused and triggers the greylist human-in-the-loop approval protocol. Add one operator per line.

|
>
<
&
;
`
$(
${