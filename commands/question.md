# Command: Question

**Description:**
Pauses execution and prompts the user for clarification or a decision. Execution will halt until the user responds.

**Child Tags:**
- `<Text>`: The question to ask the user.
- `<Options>`: A wrapper for multiple `<Option>` tags. Never include an "Other" option, that will be appended automatically.

**Example Usage:**
<Question>
    <Text>I found multiple Next.js projects. Which directory should I implement the ticket in?</Text>
    <Options>
        <Option>/frontend-v1</Option>
        <Option>/frontend-v2-beta</Option>
    </Options>
</Question>