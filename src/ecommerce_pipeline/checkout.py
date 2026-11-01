"""Checkout: the point where all three stores meet.

    MongoDB cart  --create_order()-->  PostgreSQL order (ACID)  -->  Redis cache invalidated

The PostgreSQL transaction is the commit point. The cart is only cleared and
the cache only invalidated after the order has committed, so a failed order
leaves the customer's cart intact for a retry.
"""

import redis

from ecommerce_pipeline import crud
from ecommerce_pipeline.cache import invalidate_top_products
from ecommerce_pipeline.sessions import SessionStore


class EmptyCartError(crud.OrderError):
    pass


class AnonymousSessionError(crud.OrderError):
    pass


def checkout(sessions: SessionStore, cache: redis.Redis, session_id: str) -> int:
    """Turn a session's cart into an order and return the new order_id."""
    session = sessions.get_session(session_id)
    if session is None:
        raise KeyError(f"Session {session_id} not found")
    if session["customer_id"] is None:
        raise AnonymousSessionError("Log in before checking out")
    if not session["cart"]:
        raise EmptyCartError("Cart is empty")

    items = [(line["product_id"], line["quantity"]) for line in session["cart"]]
    order_id = crud.create_order(session["customer_id"], items)  # raises -> cart untouched

    sessions.clear_cart(session_id)
    invalidate_top_products(cache)
    return order_id
