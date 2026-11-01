"""User sessions and shopping carts in MongoDB.

Why MongoDB here: a session is one self-contained, short-lived document whose
shape varies (anonymous or logged-in, device info, a cart of any length). It is
read and written as a whole on every page view, needs no joins, and should
disappear on its own when abandoned (TTL index). None of that needs relational
guarantees; the order itself is only written to PostgreSQL at checkout.

Document shape (collection `sessions`):
    {
      "_id": "3f2c...",                 # session id (UUID string)
      "customer_id": 42 | None,         # None for anonymous visitors
      "created_at": datetime, "last_active": datetime,
      "device": {...},                  # free-form client info
      "cart": [{"product_id": 7, "quantity": 2, "added_at": datetime}, ...]
    }
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection

from ecommerce_pipeline.config import Settings, load_settings

SESSION_TTL_SECONDS = 30 * 60  # abandoned sessions expire after 30 minutes idle


def _now() -> datetime:
    return datetime.now(UTC)


class SessionStore:
    """CRUD for sessions and their embedded carts."""

    def __init__(self, collection: Collection, ttl_seconds: int = SESSION_TTL_SECONDS):
        self.collection = collection
        self.ttl_seconds = ttl_seconds

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "SessionStore":
        settings = settings or load_settings()
        client: MongoClient = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=3000)
        store = cls(client[settings.mongo_db]["sessions"])
        store.ensure_indexes()
        return store

    def ensure_indexes(self) -> None:
        # TTL index: MongoDB's background task deletes documents once
        # last_active is older than ttl_seconds.
        self.collection.create_index(
            [("last_active", ASCENDING)],
            expireAfterSeconds=self.ttl_seconds,
            name="ttl_last_active",
        )
        self.collection.create_index([("customer_id", ASCENDING)], name="idx_customer_id")

    # --- sessions -------------------------------------------------------------

    def create_session(
        self, customer_id: int | None = None, device: dict[str, Any] | None = None
    ) -> str:
        now = _now()
        session_id = uuid.uuid4().hex
        self.collection.insert_one(
            {
                "_id": session_id,
                "customer_id": customer_id,
                "created_at": now,
                "last_active": now,
                "device": device or {},
                "cart": [],
            }
        )
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self.collection.find_one({"_id": session_id})

    def touch(self, session_id: str) -> bool:
        """Mark activity, pushing back the TTL expiry."""
        result = self.collection.update_one({"_id": session_id}, {"$set": {"last_active": _now()}})
        return result.matched_count == 1

    def attach_customer(self, session_id: str, customer_id: int) -> bool:
        """Link an anonymous session to a customer after login (cart is kept)."""
        result = self.collection.update_one(
            {"_id": session_id},
            {"$set": {"customer_id": customer_id, "last_active": _now()}},
        )
        return result.matched_count == 1

    def end_session(self, session_id: str) -> bool:
        return self.collection.delete_one({"_id": session_id}).deleted_count == 1

    def sessions_for_customer(self, customer_id: int) -> list[dict[str, Any]]:
        return list(self.collection.find({"customer_id": customer_id}).sort("last_active", -1))

    # --- cart -----------------------------------------------------------------

    def add_to_cart(self, session_id: str, product_id: int, quantity: int = 1) -> list[dict]:
        """Add a product, or increase its quantity if it's already in the cart."""
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        now = _now()
        # First try to bump an existing line ($ refers to the matched array element)...
        result = self.collection.update_one(
            {"_id": session_id, "cart.product_id": product_id},
            {"$inc": {"cart.$.quantity": quantity}, "$set": {"last_active": now}},
        )
        if result.matched_count == 0:
            # ...otherwise append a new line, as long as the session exists.
            result = self.collection.update_one(
                {"_id": session_id},
                {
                    "$push": {
                        "cart": {"product_id": product_id, "quantity": quantity, "added_at": now}
                    },
                    "$set": {"last_active": now},
                },
            )
            if result.matched_count == 0:
                raise KeyError(f"Session {session_id} not found")
        return self.get_cart(session_id)

    def set_quantity(self, session_id: str, product_id: int, quantity: int) -> list[dict]:
        """Set a line's quantity; 0 removes the line."""
        if quantity <= 0:
            return self.remove_from_cart(session_id, product_id)
        self.collection.update_one(
            {"_id": session_id, "cart.product_id": product_id},
            {"$set": {"cart.$.quantity": quantity, "last_active": _now()}},
        )
        return self.get_cart(session_id)

    def remove_from_cart(self, session_id: str, product_id: int) -> list[dict]:
        self.collection.update_one(
            {"_id": session_id},
            {"$pull": {"cart": {"product_id": product_id}}, "$set": {"last_active": _now()}},
        )
        return self.get_cart(session_id)

    def get_cart(self, session_id: str) -> list[dict]:
        doc = self.collection.find_one({"_id": session_id}, {"cart": 1})
        if doc is None:
            raise KeyError(f"Session {session_id} not found")
        return doc["cart"]

    def clear_cart(self, session_id: str) -> None:
        self.collection.update_one(
            {"_id": session_id}, {"$set": {"cart": [], "last_active": _now()}}
        )

    def most_carted_products(self, limit: int = 5) -> list[dict]:
        """Aggregation pipeline: which products sit in active carts most often."""
        return list(
            self.collection.aggregate(
                [
                    {"$unwind": "$cart"},
                    {
                        "$group": {
                            "_id": "$cart.product_id",
                            "carts": {"$sum": 1},
                            "units": {"$sum": "$cart.quantity"},
                        }
                    },
                    {"$sort": {"carts": -1, "_id": 1}},
                    {"$limit": limit},
                ]
            )
        )
