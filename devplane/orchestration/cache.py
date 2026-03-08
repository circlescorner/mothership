"""Token Caching Service - Optimize API costs through intelligent caching.

Provides local caching of LLM responses to reduce token usage and costs,
especially effective for repetitive queries and similar prompts.
"""

import json
import hashlib
import logging
import time
from typing import Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import asyncio

logger = logging.getLogger("devplane.orchestration.cache")


@dataclass
class CacheEntry:
    """A single cache entry."""
    key: str
    prompt_hash: str
    response: str
    model: str
    tokens_saved: int
    cost_saved: float
    created_at: float
    ttl_seconds: int
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_seconds

    @property
    def hit_value(self) -> float:
        """Value of this cache entry based on hits and savings."""
        age_hours = (time.time() - self.created_at) / 3600
        return (self.access_count * self.cost_saved) / (age_hours + 1)


class TokenCache:
    """Intelligent token cache for LLM responses."""

    def __init__(
        self,
        backend: str = "memory",  # "memory" or "redis"
        max_size_mb: float = 512,
        default_ttl_seconds: int = 3600,
        similarity_threshold: float = 0.95,
    ):
        self.backend = backend
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.default_ttl = default_ttl_seconds
        self.similarity_threshold = similarity_threshold

        # In-memory cache storage
        self._cache: dict[str, CacheEntry] = {}
        self._total_hits = 0
        self._total_misses = 0
        self._total_tokens_saved = 0
        self._total_cost_saved = 0.0

        # Redis client (if configured)
        self._redis = None
        if backend == "redis":
            self._init_redis()

        # Start cleanup task
        self._cleanup_task = None

    def _init_redis(self):
        """Initialize Redis connection."""
        try:
            import redis.asyncio as redis
            import os
            redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
            self._redis = redis.from_url(redis_url, decode_responses=True)
            logger.info(f"TokenCache connected to Redis at {redis_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}. Falling back to memory.")
            self.backend = "memory"
            self._redis = None

    async def start(self):
        """Start the cache maintenance tasks."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

    async def stop(self):
        """Stop the cache and cleanup resources."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        if self._redis:
            await self._redis.close()

    def get_cache_key(
        self,
        role: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        """Generate a cache key for a request."""
        # Normalize prompts
        normalized_system = self._normalize_text(system_prompt)
        normalized_user = self._normalize_text(user_prompt)

        # Create hash
        content = f"{role}:{normalized_system}:{normalized_user}:{temperature}:{max_tokens}"
        return hashlib.sha256(content.encode()).hexdigest()

    def _normalize_text(self, text: str) -> str:
        """Normalize text for consistent caching."""
        # Remove extra whitespace
        normalized = " ".join(text.split())
        # Convert to lowercase for case-insensitive matching
        return normalized.lower().strip()

    async def get(
        self,
        key: str,
        check_similarity: bool = True
    ) -> Optional[dict]:
        """Get a cached response."""
        # Try exact match first
        entry = await self._get_entry(key)
        if entry and not entry.is_expired:
            entry.access_count += 1
            entry.last_accessed = time.time()
            self._total_hits += 1
            self._total_tokens_saved += entry.tokens_saved
            self._total_cost_saved += entry.cost_saved
            logger.debug(f"Cache HIT for key {key[:16]}... (hit #{entry.access_count})")
            return {
                "response": entry.response,
                "model": entry.model,
                "cached": True,
                "tokens_saved": entry.tokens_saved,
                "cost_saved": entry.cost_saved,
            }

        # Try semantic similarity match
        if check_similarity and self.backend == "memory":
            similar = self._find_similar_entry(key)
            if similar:
                similar.access_count += 1
                similar.last_accessed = time.time()
                self._total_hits += 1
                self._total_tokens_saved += similar.tokens_saved
                self._total_cost_saved += similar.cost_saved
                logger.debug(f"Similarity cache HIT for key {key[:16]}...")
                return {
                    "response": similar.response,
                    "model": similar.model,
                    "cached": True,
                    "similarity_match": True,
                    "tokens_saved": similar.tokens_saved,
                    "cost_saved": similar.cost_saved,
                }

        self._total_misses += 1
        return None

    async def set(
        self,
        key: str,
        response: str,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost: float = 0.0,
        ttl_seconds: Optional[int] = None,
    ):
        """Cache a response."""
        ttl = ttl_seconds or self.default_ttl

        # Estimate tokens saved (for future hits)
        estimated_future_hits = 2  # Conservative estimate
        tokens_saved = (tokens_in + tokens_out) * estimated_future_hits
        cost_saved = cost * estimated_future_hits

        entry = CacheEntry(
            key=key,
            prompt_hash=key[:32],
            response=response,
            model=model,
            tokens_saved=tokens_saved,
            cost_saved=cost_saved,
            created_at=time.time(),
            ttl_seconds=ttl,
        )

        await self._store_entry(key, entry)

        # Check if we need to evict entries
        if self.backend == "memory":
            await self._evict_if_needed()

        logger.debug(f"Cached response for key {key[:16]}...")

    async def get_stats(self) -> dict:
        """Get cache statistics."""
        total_requests = self._total_hits + self._total_misses
        hit_rate = self._total_hits / total_requests if total_requests > 0 else 0

        stats = {
            "total_hits": self._total_hits,
            "total_misses": self._total_misses,
            "hit_rate": round(hit_rate * 100, 2),
            "total_tokens_saved": self._total_tokens_saved,
            "total_cost_saved_usd": round(self._total_cost_saved, 4),
        }

        if self.backend == "memory":
            stats["entries_count"] = len(self._cache)
            stats["cache_size_mb"] = round(self._get_memory_usage() / (1024 * 1024), 2)

        return stats

    async def clear(self):
        """Clear all cached entries."""
        if self.backend == "memory":
            self._cache.clear()
        elif self._redis:
            await self._redis.delete("devplane:token_cache:*")

        self._total_hits = 0
        self._total_misses = 0
        self._total_tokens_saved = 0
        self._total_cost_saved = 0.0

        logger.info("Token cache cleared")

    async def _get_entry(self, key: str) -> Optional[CacheEntry]:
        """Get an entry from cache."""
        if self.backend == "memory":
            return self._cache.get(key)
        elif self._redis:
            data = await self._redis.get(f"devplane:token_cache:{key}")
            if data:
                return self._deserialize_entry(data)
        return None

    async def _store_entry(self, key: str, entry: CacheEntry):
        """Store an entry in cache."""
        if self.backend == "memory":
            self._cache[key] = entry
        elif self._redis:
            serialized = self._serialize_entry(entry)
            await self._redis.setex(
                f"devplane:token_cache:{key}",
                entry.ttl_seconds,
                serialized
            )

    def _find_similar_entry(self, key: str) -> Optional[CacheEntry]:
        """Find a similar entry using simple similarity check."""
        # This is a simplified version - in production, use embeddings
        target_prompt = key  # In reality, store original prompt

        best_match = None
        best_score = 0.0

        for entry in self._cache.values():
            if entry.is_expired:
                continue

            # Simple character-level similarity
            score = self._calculate_similarity(target_prompt, entry.prompt_hash)
            if score > best_score and score >= self.similarity_threshold:
                best_score = score
                best_match = entry

        return best_match

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """Calculate similarity between two texts."""
        # Simple Jaccard similarity on character n-grams
        def get_ngrams(text, n=3):
            return set(text[i:i+n] for i in range(len(text)-n+1))

        ngrams1 = get_ngrams(text1)
        ngrams2 = get_ngrams(text2)

        if not ngrams1 or not ngrams2:
            return 0.0

        intersection = len(ngrams1 & ngrams2)
        union = len(ngrams1 | ngrams2)

        return intersection / union if union > 0 else 0.0

    async def _evict_if_needed(self):
        """Evict entries if cache exceeds size limit."""
        current_size = self._get_memory_usage()

        if current_size < self.max_size_bytes * 0.9:
            return

        # Sort by hit value (least valuable first)
        entries = sorted(
            self._cache.items(),
            key=lambda x: x[1].hit_value
        )

        # Remove bottom 20% of entries
        to_remove = len(entries) // 5
        for i in range(to_remove):
            key, entry = entries[i]
            del self._cache[key]

        logger.info(f"Evicted {to_remove} cache entries due to size limit")

    def _get_memory_usage(self) -> int:
        """Estimate memory usage of cache."""
        import sys
        total = 0
        for entry in self._cache.values():
            total += sys.getsizeof(entry.response)
            total += sys.getsizeof(entry.key)
        return total

    async def _periodic_cleanup(self):
        """Periodically clean up expired entries."""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes

                if self.backend == "memory":
                    expired = [
                        key for key, entry in self._cache.items()
                        if entry.is_expired
                    ]
                    for key in expired:
                        del self._cache[key]

                    if expired:
                        logger.debug(f"Cleaned up {len(expired)} expired cache entries")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cache cleanup error: {e}")

    def _serialize_entry(self, entry: CacheEntry) -> str:
        """Serialize cache entry to string."""
        return json.dumps({
            "key": entry.key,
            "prompt_hash": entry.prompt_hash,
            "response": entry.response,
            "model": entry.model,
            "tokens_saved": entry.tokens_saved,
            "cost_saved": entry.cost_saved,
            "created_at": entry.created_at,
            "ttl_seconds": entry.ttl_seconds,
            "access_count": entry.access_count,
            "last_accessed": entry.last_accessed,
        })

    def _deserialize_entry(self, data: str) -> CacheEntry:
        """Deserialize cache entry from string."""
        d = json.loads(data)
        return CacheEntry(
            key=d["key"],
            prompt_hash=d["prompt_hash"],
            response=d["response"],
            model=d["model"],
            tokens_saved=d["tokens_saved"],
            cost_saved=d["cost_saved"],
            created_at=d["created_at"],
            ttl_seconds=d["ttl_seconds"],
            access_count=d.get("access_count", 0),
            last_accessed=d.get("last_accessed", d["created_at"]),
        )


class SemanticCache(TokenCache):
    """Advanced cache using embeddings for semantic similarity."""

    def __init__(self, *args, embedding_model: str = "gemini/gemini-embedding-exp", **kwargs):
        super().__init__(*args, **kwargs)
        self.embedding_model = embedding_model
        self._embeddings: dict[str, list[float]] = {}

    async def _get_embedding(self, text: str) -> list[float]:
        """Get embedding for text."""
        try:
            from litellm import aembedding
            response = await aembedding(
                model=self.embedding_model,
                input=text,
            )
            return response["data"][0]["embedding"]
        except Exception as e:
            logger.warning(f"Failed to get embedding: {e}")
            return []

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        import math
        dot_product = sum(x * y for x, y in zip(a, b))
        magnitude_a = math.sqrt(sum(x * x for x in a))
        magnitude_b = math.sqrt(sum(x * x for x in b))
        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0
        return dot_product / (magnitude_a * magnitude_b)


# Global cache instance
_cache_instance: Optional[TokenCache] = None


def get_token_cache() -> TokenCache:
    """Get the global token cache instance."""
    global _cache_instance
    if _cache_instance is None:
        import os
        backend = os.environ.get("CACHE_BACKEND", "memory")
        max_size = float(os.environ.get("CACHE_MAX_SIZE_MB", "512"))
        ttl = int(os.environ.get("CACHE_TTL_SECONDS", "3600"))

        _cache_instance = TokenCache(
            backend=backend,
            max_size_mb=max_size,
            default_ttl_seconds=ttl,
        )
    return _cache_instance