# Command: MarkDone

**Description:**
The terminal command for any agent. Signals to the parent orchestrator that this agent has completely fulfilled its assigned instructions and met its explicit Definition of Done.

**Child Tags:**
- `<Result>`: The final output, answer, or technical deliverable requested.
- `<Summary>`: A brief recap of the steps taken to achieve the result.

**Example Usage:**
<MarkDone>
    <Result>The GitHub repository has been cloned to /Users/davidthele/Documents/jumbocode-ui and the branch 'feature/navbar' is checked out.</Result>
    <Summary>Ran Zsh command to clone repo, used Zsh to checkout branch, verified directory exists via ListDirectory.</Summary>
</MarkDone>