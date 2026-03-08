"""Personal Long-Term Agent - Your trusted AI companion.

A personalized agent that learns your preferences, adapts to your needs over time,
and maintains persistent long-term memory of your interactions, projects, and preferences.
"""

import json
import logging
from typing import Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger("devplane.orchestration.personal")


class PreferenceType(str, Enum):
    """Types of user preferences."""
    COMMUNICATION = "communication"    # How user likes to communicate
    CODE_STYLE = "code_style"          # Coding preferences
    WORK_HOURS = "work_hours"          # When user is active
    TOPICS = "topics"                  # Topics of interest
    TOOLS = "tools"                    # Preferred tools/tech
    FORMAT = "format"                  # Output format preferences
    DEPTH = "depth"                    # Detail level preference


@dataclass
class UserPreference:
    """A learned user preference."""
    type: PreferenceType
    key: str
    value: Any
    confidence: float = 0.5           # 0.0 to 1.0, how sure we are
    first_observed: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_observed: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    observation_count: int = 1


@dataclass
class ConversationMemory:
    """A remembered conversation."""
    id: str
    timestamp: str
    summary: str
    key_points: list[str]
    user_mood: Optional[str] = None
    topics: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    importance: float = 0.5           # 0.0 to 1.0


@dataclass
class UserProfile:
    """Complete user profile for personalization."""
    user_id: str
    name: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_interaction: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    total_interactions: int = 0
    total_tokens_consumed: int = 0

    # Core preferences
    preferences: dict[PreferenceType, list[UserPreference]] = field(default_factory=dict)

    # Conversation history (last 100 important conversations)
    conversation_memories: list[ConversationMemory] = field(default_factory=list)

    # Contextual memory
    current_projects: list[str] = field(default_factory=list)
    recent_topics: list[str] = field(default_factory=list)
    learned_facts: dict[str, str] = field(default_factory=dict)  # Key facts about user


class PersonalAgent:
    """Your personal AI companion with long-term memory and adaptation."""

    # System prompt for the personal agent
    PERSONA_PROMPT = """You are a highly personalized AI assistant who knows your user deeply.

CORE TRAITS:
- You remember past conversations, preferences, and context
- You adapt your communication style to match the user's preferences
- You proactively recall relevant information from previous interactions
- You learn and improve with every conversation
- You are trustworthy, reliable, and consistently helpful

MEMORY GUIDELINES:
- Reference previous conversations when relevant
- Apply learned preferences automatically
- Adapt tone and detail level to user's style
- Remember user’s ongoing projects and goals
- Recall important facts and dates mentioned by user

You have access to:
- User preferences and communication style
- Conversation history summaries
- Learned facts about the user
- Current projects and contexts

Always be warm, personalized, and contextually aware."""

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self.profile: Optional[UserProfile] = None
        self._loaded = False

    async def load_profile(self) -> UserProfile:
        """Load or create user profile."""
        if self._loaded and self.profile:
            return self.profile

        profile = await self._load_from_db()
        if not profile:
            profile = UserProfile(user_id=self.user_id)
            await self._save_to_db(profile)

        self.profile = profile
        self._loaded = True
        return profile

    async def chat(
        self,
        message: str,
        context: Optional[dict] = None,
        store_memory: bool = True
    ) -> dict:
        """Chat with the personal agent."""
        profile = await self.load_profile()

        # Build personalized context
        system_prompt = self._build_system_prompt(profile)
        memory_context = self._build_memory_context(message, profile)

        # Call the model
        from devplane.roles import call_with_fallback

        full_prompt = f"{memory_context}\n\nUser: {message}\n\nAssistant:"

        result = await call_with_fallback(
            role="personal",  # Use personal role for best model
            system_prompt=system_prompt,
            user_content=full_prompt,
            temperature=0.7,  # Slightly more creative for personal touch
            max_tokens=4096,
        )

        response = result["content"]

        # Update profile
        profile.total_interactions += 1
        profile.last_interaction = datetime.utcnow().isoformat()
        profile.total_tokens_consumed += result.get("tokens_in", 0) + result.get("tokens_out", 0)

        # Extract and learn preferences
        await self._learn_from_interaction(message, response, profile)

        # Store conversation memory
        if store_memory:
            await self._store_conversation_memory(message, response, profile)

        await self._save_to_db(profile)

        return {
            "response": response,
            "tokens_used": result.get("tokens_in", 0) + result.get("tokens_out", 0),
            "cost": result.get("cost", 0),
            "memory_references": self._extract_memory_refs(memory_context),
        }

    async def recall(self, query: str, limit: int = 5) -> list[dict]:
        """Recall relevant memories."""
        profile = await self.load_profile()

        # Search conversation memories
        relevant = []
        for mem in profile.conversation_memories:
            score = self._relevance_score(query, mem)
            if score > 0.3:
                relevant.append({"memory": mem, "score": score})

        # Sort by relevance and importance
        relevant.sort(key=lambda x: (x["score"] * x["memory"].importance), reverse=True)

        return [
            {
                "timestamp": r["memory"].timestamp,
                "summary": r["memory"].summary,
                "key_points": r["memory"].key_points,
                "topics": r["memory"].topics,
                "relevance": r["score"],
            }
            for r in relevant[:limit]
        ]

    async def add_preference(
        self,
        pref_type: PreferenceType,
        key: str,
        value: Any,
        confidence: float = 0.8
    ):
        """Manually add a user preference."""
        profile = await self.load_profile()

        if pref_type not in profile.preferences:
            profile.preferences[pref_type] = []

        # Check if preference already exists
        existing = next(
            (p for p in profile.preferences[pref_type] if p.key == key),
            None
        )

        if existing:
            existing.value = value
            existing.confidence = confidence
            existing.observation_count += 1
            existing.last_observed = datetime.utcnow().isoformat()
        else:
            profile.preferences[pref_type].append(
                UserPreference(
                    type=pref_type,
                    key=key,
                    value=value,
                    confidence=confidence,
                )
            )

        await self._save_to_db(profile)

    async def get_preferences(self, pref_type: Optional[PreferenceType] = None) -> dict:
        """Get user preferences."""
        profile = await self.load_profile()

        if pref_type:
            return {
                p.key: {"value": p.value, "confidence": p.confidence}
                for p in profile.preferences.get(pref_type, [])
            }

        return {
            t.value: {
                p.key: {"value": p.value, "confidence": p.confidence}
                for p in prefs
            }
            for t, prefs in profile.preferences.items()
        }

    async def add_learned_fact(self, key: str, value: str):
        """Add a learned fact about the user."""
        profile = await self.load_profile()
        profile.learned_facts[key] = value
        await self._save_to_db(profile)

    async def set_current_project(self, project_name: str):
        """Set the current project context."""
        profile = await self.load_profile()
        if project_name not in profile.current_projects:
            profile.current_projects.insert(0, project_name)
            profile.current_projects = profile.current_projects[:5]  # Keep last 5
        await self._save_to_db(profile)

    def _build_system_prompt(self, profile: UserProfile) -> str:
        """Build personalized system prompt."""
        prompt = self.PERSONA_PROMPT

        # Add name if known
        if profile.name:
            prompt += f"\n\nThe user's name is {profile.name}."

        # Add communication preferences
        comm_prefs = profile.preferences.get(PreferenceType.COMMUNICATION, [])
        for pref in comm_prefs:
            if pref.confidence > 0.6:
                prompt += f"\n- User prefers {pref.key}: {pref.value}"

        # Add code style preferences
        code_prefs = profile.preferences.get(PreferenceType.CODE_STYLE, [])
        for pref in code_prefs:
            if pref.confidence > 0.6:
                prompt += f"\n- For coding: {pref.key} = {pref.value}"

        # Add depth preference
        depth_prefs = profile.preferences.get(PreferenceType.DEPTH, [])
        for pref in depth_prefs:
            if pref.confidence > 0.6:
                prompt += f"\n- Detail level: {pref.value}"

        # Add learned facts
        if profile.learned_facts:
            prompt += "\n\nIMPORTANT FACTS ABOUT USER:"
            for key, value in list(profile.learned_facts.items())[:10]:
                prompt += f"\n- {key}: {value}"

        # Add current projects
        if profile.current_projects:
            prompt += f"\n\nCURRENT PROJECTS: {', '.join(profile.current_projects)}"

        return prompt

    def _build_memory_context(self, message: str, profile: UserProfile) -> str:
        """Build context from relevant memories."""
        context_parts = []

        # Find relevant conversation memories
        relevant = []
        for mem in profile.conversation_memories[-20:]:  # Check last 20
            score = self._relevance_score(message, mem)
            if score > 0.5:
                relevant.append((mem, score))

        relevant.sort(key=lambda x: x[1], reverse=True)

        if relevant:
            context_parts.append("RELEVANT PAST CONVERSATIONS:")
            for mem, score in relevant[:3]:
                context_parts.append(f"- {mem.summary}")
                if mem.action_items:
                    context_parts.append(f"  Action items: {', '.join(mem.action_items)}")

        return "\n".join(context_parts) if context_parts else ""

    def _relevance_score(self, query: str, memory: ConversationMemory) -> float:
        """Calculate relevance score between query and memory."""
        query_words = set(query.lower().split())

        # Check summary
        summary_words = set(memory.summary.lower().split())
        summary_overlap = len(query_words & summary_words) / len(query_words) if query_words else 0

        # Check topics
        topic_overlap = 0
        for topic in memory.topics:
            if any(word in topic.lower() for word in query_words):
                topic_overlap += 0.3

        # Check key points
        key_point_overlap = 0
        for point in memory.key_points:
            point_words = set(point.lower().split())
            overlap = len(query_words & point_words) / len(query_words) if query_words else 0
            key_point_overlap = max(key_point_overlap, overlap)

        return max(summary_overlap, topic_overlap, key_point_overlap)

    async def _learn_from_interaction(
        self,
        message: str,
        response: str,
        profile: UserProfile
    ):
        """Learn preferences from user interaction."""
        # Simple heuristic-based learning
        message_lower = message.lower()

        # Learn communication style
        if any(word in message_lower for word in ["short", "brief", "quick"]):
            await self._update_preference(
                profile, PreferenceType.COMMUNICATION, "verbosity", "concise"
            )
        elif any(word in message_lower for word in ["detailed", "explain", "elaborate"]):
            await self._update_preference(
                profile, PreferenceType.COMMUNICATION, "verbosity", "detailed"
            )

        # Learn code style
        if "python" in message_lower:
            await self._update_preference(profile, PreferenceType.TOOLS, "language", "python")
        if "typescript" in message_lower or "javascript" in message_lower:
            await self._update_preference(profile, PreferenceType.TOOLS, "language", "javascript")

        # Learn topics of interest
        topics = self._extract_topics(message)
        for topic in topics:
            if topic not in profile.recent_topics:
                profile.recent_topics.insert(0, topic)
                profile.recent_topics = profile.recent_topics[:20]

    async def _update_preference(
        self,
        profile: UserProfile,
        pref_type: PreferenceType,
        key: str,
        value: Any
    ):
        """Update a preference with learning."""
        if pref_type not in profile.preferences:
            profile.preferences[pref_type] = []

        existing = next(
            (p for p in profile.preferences[pref_type] if p.key == key),
            None
        )

        if existing:
            if existing.value == value:
                existing.confidence = min(1.0, existing.confidence + 0.1)
                existing.observation_count += 1
            else:
                # Conflicting preference - reduce confidence
                existing.confidence *= 0.8
                if existing.confidence < 0.3:
                    existing.value = value
                    existing.confidence = 0.5
            existing.last_observed = datetime.utcnow().isoformat()
        else:
            profile.preferences[pref_type].append(
                UserPreference(
                    type=pref_type,
                    key=key,
                    value=value,
                    confidence=0.5,
                )
            )

    def _extract_topics(self, message: str) -> list[str]:
        """Extract topics from message."""
        # Simple keyword-based topic extraction
        tech_keywords = [
            "python", "javascript", "typescript", "rust", "go", "java",
            "react", "vue", "angular", "node", "django", "fastapi",
            "docker", "kubernetes", "aws", "gcp", "azure",
            "machine learning", "ai", "database", "api", "frontend", "backend"
        ]

        found = []
        message_lower = message.lower()
        for keyword in tech_keywords:
            if keyword in message_lower:
                found.append(keyword)

        return found

    async def _store_conversation_memory(
        self,
        message: str,
        response: str,
        profile: UserProfile
    ):
        """Store a conversation summary in memory."""
        import uuid

        # Generate summary (in production, use LLM to summarize)
        summary = f"User asked about: {message[:100]}..."

        # Extract key points
        key_points = [f"User: {message[:200]}", f"Assistant provided: {response[:200]}"]

        # Extract topics
        topics = self._extract_topics(message + " " + response)

        # Extract action items (look for TODO patterns)
        action_items = []
        if "todo" in message.lower() or "task" in message.lower():
            action_items.append("Follow up on task discussion")

        memory = ConversationMemory(
            id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            summary=summary,
            key_points=key_points,
            topics=topics,
            action_items=action_items,
            importance=0.5 if not action_items else 0.8,
        )

        profile.conversation_memories.append(memory)

        # Keep only important memories (last 100)
        profile.conversation_memories.sort(key=lambda m: m.importance, reverse=True)
        profile.conversation_memories = profile.conversation_memories[:100]

    def _extract_memory_refs(self, memory_context: str) -> list[str]:
        """Extract memory references from context."""
        if not memory_context:
            return []

        refs = []
        for line in memory_context.split("\n"):
            if line.startswith("- "):
                refs.append(line[2:])
        return refs[:3]

    async def _load_from_db(self) -> Optional[UserProfile]:
        """Load profile from database."""
        from devplane.db import get_db
        db = await get_db()
        try:
            row = await db.execute(
                "SELECT data FROM user_profiles WHERE user_id = ?",
                (self.user_id,)
            )
            data = await row.fetchone()
            if data:
                return self._dict_to_profile(json.loads(data["data"]))
            return None
        finally:
            await db.close()

    async def _save_to_db(self, profile: UserProfile):
        """Save profile to database."""
        from devplane.db import get_db
        db = await get_db()
        try:
            await db.execute("""
                INSERT OR REPLACE INTO user_profiles (user_id, data, updated_at)
                VALUES (?, ?, ?)
            """, (
                self.user_id,
                json.dumps(self._profile_to_dict(profile)),
                datetime.utcnow().isoformat()
            ))
            await db.commit()
        finally:
            await db.close()

    def _profile_to_dict(self, profile: UserProfile) -> dict:
        """Convert profile to dictionary."""
        return {
            "user_id": profile.user_id,
            "name": profile.name,
            "created_at": profile.created_at,
            "last_interaction": profile.last_interaction,
            "total_interactions": profile.total_interactions,
            "total_tokens_consumed": profile.total_tokens_consumed,
            "preferences": {
                t.value: [
                    {
                        "type": p.type.value,
                        "key": p.key,
                        "value": p.value,
                        "confidence": p.confidence,
                        "first_observed": p.first_observed,
                        "last_observed": p.last_observed,
                        "observation_count": p.observation_count,
                    }
                    for p in prefs
                ]
                for t, prefs in profile.preferences.items()
            },
            "conversation_memories": [
                {
                    "id": m.id,
                    "timestamp": m.timestamp,
                    "summary": m.summary,
                    "key_points": m.key_points,
                    "user_mood": m.user_mood,
                    "topics": m.topics,
                    "action_items": m.action_items,
                    "importance": m.importance,
                }
                for m in profile.conversation_memories
            ],
            "current_projects": profile.current_projects,
            "recent_topics": profile.recent_topics,
            "learned_facts": profile.learned_facts,
        }

    def _dict_to_profile(self, data: dict) -> UserProfile:
        """Convert dictionary to profile."""
        profile = UserProfile(
            user_id=data["user_id"],
            name=data.get("name"),
            created_at=data["created_at"],
            last_interaction=data["last_interaction"],
            total_interactions=data.get("total_interactions", 0),
            total_tokens_consumed=data.get("total_tokens_consumed", 0),
            current_projects=data.get("current_projects", []),
            recent_topics=data.get("recent_topics", []),
            learned_facts=data.get("learned_facts", {}),
        )

        # Load preferences
        for type_str, prefs_data in data.get("preferences", {}).items():
            pref_type = PreferenceType(type_str)
            profile.preferences[pref_type] = [
                UserPreference(
                    type=pref_type,
                    key=p["key"],
                    value=p["value"],
                    confidence=p["confidence"],
                    first_observed=p["first_observed"],
                    last_observed=p["last_observed"],
                    observation_count=p["observation_count"],
                )
                for p in prefs_data
            ]

        # Load memories
        profile.conversation_memories = [
            ConversationMemory(
                id=m["id"],
                timestamp=m["timestamp"],
                summary=m["summary"],
                key_points=m["key_points"],
                user_mood=m.get("user_mood"),
                topics=m.get("topics", []),
                action_items=m.get("action_items", []),
                importance=m.get("importance", 0.5),
            )
            for m in data.get("conversation_memories", [])
        ]

        return profile