"""The application's root bundles: only CacheBundle, in every environment."""

from __future__ import annotations

from xtr_cache.bundle import CacheBundle

BUNDLES = {CacheBundle: {"all": True}}
