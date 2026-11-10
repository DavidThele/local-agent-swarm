# Command: Chrome

**Description:**
Controls a persistent, headed instance of Google Chrome attached to the user's daily-driver profile. It extracts the interactive DOM and assigns a unique numerical ID to every visible button, link, and input.

**Attributes:**
- `action` (required): The action to perform (`navigate`, `click`, `type`, `scroll`, `close`).
- `url` (optional): Required if action is `navigate`.
- `target_id` (optional): Required if action is `click` or `type`. The numerical ID of the element from the most recently returned DOM.
- `direction` (optional): Required if action is `scroll` (`up` or `down`).

**Child Tags:**
- `<Text>`: Required if action is `type`. The text to input into the field.

**Example Usage:**
<Chrome action="navigate" url="https://linear.app" />

<Chrome action="type" target_id="42">
    <Text>Navbar refactor</Text>
</Chrome>

<Chrome action="click" target_id="18" />