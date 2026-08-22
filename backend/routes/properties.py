"""
routes/properties.py — the contractor's public catalog endpoints.

  GET /properties        -> all listings (public fields only; no floor price)
  GET /properties/{id}   -> one listing

The private ``floor_price`` (the seller's reservation) is stripped by
``catalog.public`` and never reaches a client.
"""
from __future__ import annotations

import catalog


def list_properties(params, body, query):
    return 200, {"properties": catalog.all_public()}


def get_property(params, body, query):
    p = catalog.get_public(params["id"])
    if p is None:
        return 404, {"error": "property not found"}
    return 200, p
