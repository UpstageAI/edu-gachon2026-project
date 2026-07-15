"""Persistence adapters for FinBrief storage backends."""

from app.repositories.memory import create_memory_repositories
from app.repositories.protocols import (
    CardRepository,
    NewsRepository,
    RepositoryBundle,
    SubscriptionRepository,
    TopicRepository,
    UserRepository,
)
from app.repositories.supabase import SupabaseIngestionRepository, create_supabase_repositories

__all__ = [
    "CardRepository",
    "NewsRepository",
    "RepositoryBundle",
    "SubscriptionRepository",
    "TopicRepository",
    "UserRepository",
    "SupabaseIngestionRepository",
    "create_memory_repositories",
    "create_supabase_repositories",
]
