import chromadb
import uuid
from pathlib import Path
from typing import List, Dict, Any
from infrastructure.debug_colors import debug_print

def get_db_client(global_dir: str = "~/.agents"):
    """Initializes and returns a persistent ChromaDB client."""
    db_path = Path(global_dir).expanduser() / "db"
    db_path.mkdir(parents=True, exist_ok=True)
    
    client = chromadb.PersistentClient(path=str(db_path))
    # We use a default collection for the semantic memory
    collection = client.get_or_create_collection(name="semantic_memory")
    return collection

def add_chunk(text: str, metadata: Dict[str, Any] = {}) -> str:
    """Adds a new chunk to the database and returns its generated ID."""
    collection = get_db_client()
    chunk_id = f"chunk_{uuid.uuid4().hex[:12]}"
    
    collection.add(
        documents=[text],
        metadatas=[metadata or {}],
        ids=[chunk_id]
    )
    return chunk_id

def delete_chunk(chunk_id: str):
    """Deletes a chunk from the database by its ID."""
    collection = get_db_client()
    collection.delete(ids=[chunk_id])

def clear():
    """Clears all chunks from the database."""
    collection = get_db_client()
    existing_ids = collection.get()["ids"]
    if existing_ids:
        collection.delete(ids=existing_ids)
    debug_print("[DbManager] DB cleared.", "success")

    
def search_similar_chunks(query_text: str, n_results: int = 5) -> List[Dict[str, Any]]:
    """Searches for chunks semantically similar to the query."""
    collection = get_db_client()
    
    # Handle empty collection case gracefully
    if collection.count() == 0:
        return []
        
    results = collection.query(
        query_texts=[query_text],
        n_results=min(n_results, collection.count())
    )
    
    formatted_results = []
    if results['documents'] and results['documents'][0]:
        for i in range(len(results['documents'][0])):
            formatted_results.append({
                "id": results['ids'][0][i],
                "text": results['documents'][0][i],
                "metadata": results['metadatas'][0][i] if results['metadatas'] else {}
            })
            
    return formatted_results

if __name__ == "__main__":
    # Test DB setup
    debug_print("[DbManager] Testing ChromaDB setup...", "system")
    c_id = add_chunk("David uses React for JumboCode frontend development.", {"timestamp": "2026-10-25"})
    debug_print(f"[DbManager] Added chunk: {c_id}", "success")
    
    matches = search_similar_chunks("What framework does David use for frontend?")
    for match in matches:
        debug_print(f"[DbManager] Match {match['id']}: {match['text']}", "data")
        
    delete_chunk(c_id)
    debug_print("[DbManager] Cleaned up test chunk.", "success")