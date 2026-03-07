"""Persistent AI Memory — vector store + conversation history.

Stores chain outputs and context in both SQLite (full text) and
Qdrant (embeddings) for semantic retrieval. Memory improves
response quality over time by injecting relevant past context.
"""

import json
import logging
import hashlib
from datetime import datetime
from typing import Optional
from devplane.db import get_db

logger = logging.getLogger("devplane.memory")

# ─── Embedding Model ─────────────────────────────────────────────────────────

EMBED_MODEL = "gemini/text-embedding-004"  # Free tier
EMBED_DIM = 768


async def embed_text(text: str) -> list[float]:
    """Generate embedding vector for text using LiteLLM."""
    try:
        from litellm import aembedding
        response = await aembedding(model=EMBED_MODEL, input=[text])
        return response.data[0]["embedding"]
    except Exception as e:
        logger.warning(f"Embedding failed (falling back to hash): {e}")
        # Fallback: simple hash-based pseudo-embedding for when API is unavailable
        return _hash_embed(text)


def _hash_embed(text: str) -> list[float]:
    """Deterministic pseudo-embedding from text hash. Used as fallback."""
    import struct
    h = hashlib.sha256(text.encode()).digest() * (EMBED_DIM // 32 + 1)
    floats = [struct.unpack('f', h[i:i+4])[0] % 1.0 for i in range(0, EMBED_DIM * 4, 4)]
    return floats[:EMBED_DIM]


# ─── Memory Store ────────────────────────────────────────────────────────────

async def remember(content: str, role: str = "assistant",
                   project_id: int = 0, metadata: dict = None) -> int:
    """Store a memory chunk with embedding for later retrieval.
    
    Args:
        content: Text to store
        role: 'user' or 'assistant'
        project_id: Project context
        metadata: Extra metadata (tier, model, cost, etc.)
    
    Returns:
        Memory ID
    """
    embedding = await embed_text(content)
    embed_id = hashlib.md5(content.encode()).hexdigest()[:12]

    db = await get_db()
    try:
        await db.execute("""
            INSERT INTO memories (project_id, content, role, embedding_id, metadata_json)
            VALUES (?, ?, ?, ?, ?)
        """, (
            project_id, content, role, embed_id,
            json.dumps(metadata or {})
        ))
        await db.commit()
        row = await db.execute("SELECT last_insert_rowid()")
        memory_id = (await row.fetchone())[0]

        # Store embedding in Qdrant if available
        try:
            await _store_in_qdrant(embed_id, embedding, content, project_id, metadata)
        except Exception as e:
            logger.debug(f"Qdrant storage skipped: {e}")

        logger.info(f"Stored memory #{memory_id} ({len(content)} chars) for project {project_id}")
        return memory_id
    finally:
        await db.close()


async def recall(query: str, project_id: int = 0, k: int = 5) -> list[dict]:
    """Semantic search for relevant past context.
    
    Args:
        query: Search query
        project_id: Filter by project
        k: Number of results
    
    Returns:
        List of memory dicts with content and metadata
    """
    # Try Qdrant first for semantic search
    try:
        results = await _search_qdrant(query, project_id, k)
        if results:
            return results
    except Exception as e:
        logger.debug(f"Qdrant search failed, using SQLite: {e}")

    # Fallback: keyword search in SQLite
    db = await get_db()
    try:
        # Simple LIKE search — not ideal but works without vector DB
        words = query.split()[:5]  # Top 5 words
        conditions = " OR ".join(["content LIKE ?" for _ in words])
        params = [f"%{w}%" for w in words]

        if project_id:
            conditions = f"project_id = ? AND ({conditions})"
            params = [project_id] + params

        rows = await db.execute(f"""
            SELECT content, role, metadata_json, created_at
            FROM memories WHERE {conditions}
            ORDER BY created_at DESC LIMIT ?
        """, params + [k])

        return [
            {
                "content": r["content"],
                "role": r["role"],
                "metadata": json.loads(r["metadata_json"] or "{}"),
                "created_at": r["created_at"],
                "source": "sqlite"
            }
            for r in await rows.fetchall()
        ]
    finally:
        await db.close()


async def get_history(project_id: int = 0, limit: int = 10) -> list[dict]:
    """Get recent conversation history for a project."""
    db = await get_db()
    try:
        rows = await db.execute("""
            SELECT content, role, metadata_json, created_at FROM memories
            WHERE project_id = ?
            ORDER BY created_at DESC LIMIT ?
        """, (project_id, limit))
        return [
            {
                "content": r["content"],
                "role": r["role"],
                "metadata": json.loads(r["metadata_json"] or "{}"),
                "created_at": r["created_at"],
            }
            for r in await rows.fetchall()
        ]
    finally:
        await db.close()


async def get_memory_stats(project_id: int = 0) -> dict:
    """Get memory statistics for the dashboard."""
    db = await get_db()
    try:
        total_row = await db.execute("SELECT COUNT(*) as c FROM memories WHERE project_id = ?", (project_id,))
        total = (await total_row.fetchone())["c"]

        all_row = await db.execute("SELECT COUNT(*) as c FROM memories")
        total_all = (await all_row.fetchone())["c"]

        return {
            "total_memories": total_all,
            "project_memories": total,
            "qdrant_connected": await _check_qdrant(),
        }
    finally:
        await db.close()


async def clear_memory(project_id: int = 0) -> dict:
    """Clear all memories for a project."""
    db = await get_db()
    try:
        if project_id:
            await db.execute("DELETE FROM memories WHERE project_id = ?", (project_id,))
        else:
            await db.execute("DELETE FROM memories")
        await db.commit()
        return {"status": "cleared"}
    finally:
        await db.close()


async def search_memory(query: str, project_id: int = 0, limit: int = 20) -> list[dict]:
    """Full-text search across memories."""
    db = await get_db()
    try:
        rows = await db.execute("""
            SELECT content, role, metadata_json, created_at FROM memories
            WHERE project_id = ? AND content LIKE ?
            ORDER BY created_at DESC LIMIT ?
        """, (project_id, f"%{query}%", limit))
        return [dict(r) for r in await rows.fetchall()]
    finally:
        await db.close()


# ─── Qdrant Integration (Optional) ───────────────────────────────────────────

QDRANT_COLLECTION = "devplane_memory"


async def _check_qdrant() -> bool:
    """Check if Qdrant is available."""
    import os
    url = os.environ.get("QDRANT_URL", "")
    return bool(url)


async def _store_in_qdrant(embed_id: str, embedding: list, content: str,
                           project_id: int, metadata: dict = None):
    """Store embedding in Qdrant vector DB."""
    import os
    url = os.environ.get("QDRANT_URL", "")
    key = os.environ.get("QDRANT_KEY", "")
    if not url:
        return

    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct, VectorParams, Distance

    client = QdrantClient(url=url, api_key=key if key else None)

    # Ensure collection exists
    try:
        client.get_collection(QDRANT_COLLECTION)
    except Exception:
        client.create_collection(
            QDRANT_COLLECTION,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE)
        )

    point = PointStruct(
        id=abs(hash(embed_id)) % (2**63),
        vector=embedding,
        payload={
            "content": content[:2000],  # Limit stored text
            "project_id": project_id,
            "metadata": metadata or {},
            "created_at": datetime.utcnow().isoformat(),
        }
    )
    client.upsert(QDRANT_COLLECTION, [point])


async def _search_qdrant(query: str, project_id: int, k: int) -> list[dict]:
    """Search Qdrant for similar memories."""
    import os
    url = os.environ.get("QDRANT_URL", "")
    key = os.environ.get("QDRANT_KEY", "")
    if not url:
        return []

    from qdrant_client import QdrantClient
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    client = QdrantClient(url=url, api_key=key if key else None)
    embedding = await embed_text(query)

    filter_cond = None
    if project_id:
        filter_cond = Filter(must=[
            FieldCondition(key="project_id", match=MatchValue(value=project_id))
        ])

    try:
        results = client.search(
            collection_name=QDRANT_COLLECTION,
            query_vector=embedding,
            query_filter=filter_cond,
            limit=k,
        )
        return [
            {
                "content": r.payload.get("content", ""),
                "metadata": r.payload.get("metadata", {}),
                "score": r.score,
                "source": "qdrant",
            }
            for r in results
        ]
    except Exception:
        return []
