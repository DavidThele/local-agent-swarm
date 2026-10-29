import json
from db.db_manager import get_db_client
from infrastructure.debug_colors import debug_print

def get_all_chunks() -> list:
    """Fetches every chunk currently stored in the database."""
    collection = get_db_client()
    
    # In ChromaDB, calling get() without arguments returns everything
    results = collection.get()
    
    chunks = []
    if results and results.get('ids'):
        for i in range(len(results['ids'])):
            chunks.append({
                "id": results['ids'][i],
                "text": results['documents'][i] if results.get('documents') else "",
                "metadata": results['metadatas'][i] if results.get('metadatas') else {}
            })
            
    return chunks

def print_all_chunks():
    """Prints all chunks in a highly readable terminal format."""
    chunks = get_all_chunks()
    
    debug_print(f"\n[DbTester] Chroma DB status: {len(chunks)} chunks", "system")
    if not chunks:
        debug_print("[DbTester] Database is completely empty.", "warning")
        return

    for c in chunks:
        debug_print(f"\n[DbTester] ID: {c['id']}", "data")
        debug_print(f"[DbTester] Metadata: {json.dumps(c['metadata'])}", "data")
        
        # Truncate text if it's massively long just for the terminal view
        text = c['text']
        debug_print(f"[DbTester] Text: {text}", "data")
    debug_print("[DbTester] Finished listing chunks.\n", "system")

def delete_all_chunks():
    """Wipes the entire database completely clean."""
    collection = get_db_client()
    results = collection.get()
    
    if results and results.get('ids'):
        ids_to_delete = results['ids']
        collection.delete(ids=ids_to_delete)
        debug_print(f"[DbTester] Purged {len(ids_to_delete)} chunks. Database is now empty.", "success")
    else:
        debug_print("[DbTester] Database is already empty.", "warning")

def delete_specific_chunks(chunk_ids: list):
    """Deletes specific chunks by a list of their exact string IDs."""
    collection = get_db_client()
    try:
        collection.delete(ids=chunk_ids)
        debug_print(f"[DbTester] Deleted {len(chunk_ids)} chunks: {chunk_ids}", "success")
    except Exception as e:
        debug_print(f"[DbTester] Failed to delete chunks: {e}", "error")
