# Command: SearchDB

**Description:**
Queries the semantic memory database for historical context, past work, user preferences, or system logs.

**Attributes:**
- `n_results` (optional): The maximum number of relevant chunks to retrieve. Defaults to 5. Must be an integer.

**Child Tags:**
- `<Query>`: The natural language search string to match against the vector database.

**Example Usage:**
<SearchDB n_results="3">
    <Query>What are David's preferred Tailwind CSS naming conventions for React components?</Query>
</SearchDB>