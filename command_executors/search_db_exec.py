import sys
from pathlib import Path
from db.db_manager import search_similar_chunks

def execute(attributes: dict, content: dict, context_state: dict) -> str:
    # Handle cases where the LLM passes <Query> as a dictionary key or raw string
    if isinstance(content, dict):
        query = content.get("Query", "")
        if isinstance(query, list):
            query = query[0]
    else:
        query = content

    if not query:
        return "[Error] SearchDB requires a <Query> tag with text."
        
    try:
        n_results = int(attributes.get("n_results", 5))
    except (TypeError, ValueError):
        return "[Error] SearchDB n_results must be an integer."
    if n_results <= 0:
        return "[Error] SearchDB n_results must be greater than zero."
    
    try:
        results = search_similar_chunks(query, n_results=n_results)
        
        if not results:
            return "[System] No relevant information found in semantic memory."
            
        formatted_output = "--- Semantic Database Results ---\n"
        for i, res in enumerate(results, 1):
            timestamp = res.get("metadata", {}).get("timestamp", "Unknown Date")
            formatted_output += f"[{i}] (Date: {timestamp}):\n{res['text']}\n\n"
            
        return formatted_output.strip()
    except Exception as e:
        return f"[Error] Database search failed: {str(e)}"