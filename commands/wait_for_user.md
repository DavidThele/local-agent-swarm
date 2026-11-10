# Command: WaitForUser

**Description:**
Pauses execution and alerts the user in the terminal that manual intervention is required on their screen (e.g., solving a CAPTCHA, entering a 2FA code, or logging into a gated website). Execution will resume once the user hits Enter.

**Child Tags:**
- `<Reason>`: The explanation of what you need the user to do on their screen.

**Example Usage:**
<WaitForUser>
    <Reason>Please log into Linear.app and handle the 2FA prompt. Press Enter in the terminal when you are at the dashboard.</Reason>
</WaitForUser>