---
name: xtr-cache
description: How to cache values with xtr-cache and type against xtr-cache-contracts — fetch-or-compute pools in memory, in files or in Redis, chained or tag-aware, with stampede protection. Use when code should remember an expensive result, needs a TTL or an expiry, invalidation by tag, a cache cleared or pruned, a Redis or filesystem cache pool, encrypted cached values, or a test that must freeze a cache lifetime; also when adding CacheBundle and named pools to an application on xtr-dependency-injection, or reading the cache:pool:* commands.
---

# xtr-cache

A cache pool takes the key and the function that computes the value, and decides when to run it:
`await cache.get(key, callback)`. That one call is what makes a miss computed once for every
caller waiting on it, and a hot value refreshed before it expires. Every call that reaches a
backend is awaited, and a backend failing never raises: reads miss, writes return `False`, and
the pool logs why.

## Quick reference

- Type application code against the contracts: `from xtr_cache_contracts import CacheInterface`.
  The implementations re-export the same objects, so either import path works, but a class that
  only caches should depend on `xtr-cache-contracts`.
- Fetch-or-compute: `value = await cache.get("invoice.7", load_invoice)`. The callback is an
  `async def` taking the item and returning the value.
- Set the lifetime inside the callback, on the item: `item.expires_after(600)` or
  `item.expires_at(moment)`. Tags too: `item.tag(["customer.7"])`.
- Drop one key: `await cache.delete("invoice.7")`. Drop by tag:
  `await cache.invalidate_tags(["customer.7"])` on a `TagAwareAdapter`.
- Need a hit told apart from a miss, several keys at once, or batched writes? Drop to the item
  pool: `get_item`, `get_items`, `save`, `save_deferred`, `commit`, `delete_item`, `clear`.
- Keys and tags are non-empty strings with none of `{}()/\@:` (`RESERVED_CHARACTERS`); letters,
  digits, `_` and `.` under 64 characters work everywhere. One key holds one type.
- In an application: activate `CacheBundle`, name pools in `CacheConfig`, inject
  `CacheInterface` for the `app` pool and `Annotated[CacheInterface, Target("name")]` for another.

## Cache a value

```python
from xtr_cache_contracts import CacheInterface, ItemInterface


class Invoices:
    def __init__(self, cache: CacheInterface) -> None:
        self._cache = cache

    async def get(self, invoice_id: int) -> Invoice:
        async def load(item: ItemInterface) -> Invoice:
            item.expires_after(600)  # seconds, or a timedelta
            return await self._fetch(invoice_id)

        return await self._cache.get(f"invoice.{invoice_id}", load)

    async def forget(self, invoice_id: int) -> None:
        _ = await self._cache.delete(f"invoice.{invoice_id}")
```

If the callback raises, nothing is stored and the error reaches the caller unchanged. An item
whose lifetime is zero or less is removed instead of saved. `item.expires_after(None)` falls back
to the pool's `default_lifetime`.

Pass a `Metadata` dict to learn about the read — the pool fills in `expiry` (Unix timestamp),
`ctime` (milliseconds the value took to compute), `tags`, and `save_failed` when a computed value
could not be stored:

```python
from xtr_cache_contracts import Metadata

metadata: Metadata = {}
report = await cache.get("report.daily", build_report, metadata=metadata)
if metadata.get("save_failed"):
    ...
```

## Work with items

Use the item level only when fetch-or-compute cannot answer the question.

```python
item = await pool.get_item("rate.42")
if not item.is_hit():
    _ = await pool.save(item.set(0).expires_after(60))

items = await pool.get_items(["a", "b", "c"])  # an item per key, hit or miss, in order
_ = await pool.save_deferred(item)  # queued ...
_ = await pool.commit()  # ... written in one batch
```

`None` is a value like any other — `is_hit()` is the only way to tell it from a miss. Changing an
item reaches the backend only once it is saved.

## Pick an adapter

| Adapter | Keeps values | Build it |
| --- | --- | --- |
| `ArrayAdapter` | this process's memory | `ArrayAdapter(60, max_items=1000)` |
| `FilesystemAdapter` | one file each under a directory | `FilesystemAdapter("app", 60, "/var/cache/app")` |
| `RedisAdapter` | a Redis or Valkey server | `RedisAdapter.from_url("redis://cache:6379/0", "app")` |
| `NullAdapter` | nowhere; every read misses | `NullAdapter()` |
| `ChainAdapter` | several pools, fastest first | `ChainAdapter([ArrayAdapter(), redis])` |
| `TagAwareAdapter` | any pool, plus tag versions | `TagAwareAdapter(redis)` |

Shared arguments: `namespace` (first positional, except on `ArrayAdapter` and `ChainAdapter`,
which have no use for one) and `default_lifetime` in seconds, `0` keeping values until deleted.
`pool.with_sub_namespace("tenant42")` returns a view whose keys live under `tenant42` and can be
cleared on their own. `AdapterFactory.create_adapter(dsn, namespace, default_lifetime)` builds any
of them from what a configuration names.

See [references/adapters.md](references/adapters.md) for each adapter's own options, the DSNs the
factory reads, and the rules on Redis namespaces and filesystem directories.

## Invalidate by tag

```python
from xtr_cache import TagAwareAdapter

cache = TagAwareAdapter(RedisAdapter.from_url("redis://cache:6379/0", "app"))


async def load_order(item: ItemInterface) -> Order:
    item.tag([f"customer.{customer_id}", "orders"])
    return await orders.fetch(order_id)


_ = await cache.get(f"order.{order_id}", load_order)
_ = await cache.invalidate_tags([f"customer.{customer_id}"])
```

Invalidating costs the same however many items carry the tag: each tag has a version, and an item
is a hit only while every version it was saved with is unchanged. Versions read are trusted for
`known_tag_versions_ttl` seconds (0.15 by default), which is how soon an invalidation elsewhere
reaches this process. Calling `item.tag(...)` on a pool that is not tag-aware raises `LogicError`.

## Stampede protection and marshallers

`get()` already computes a missed key once per process, however many callers wait on it. Two knobs
on top: `cache.set_lock_registry(LockRegistry(...))` extends that to every process sharing the
lock store, and `beta` on each `get()` tunes refreshing a value shortly before it expires (`0`
off, `math.inf` now, `None` the pool's own `1.0`).

Adapters that store bytes encode values with a `MarshallerInterface`, pickle by default. On a
backend anything else can write to, use `SodiumMarshaller` instead: it encrypts, authenticates, and
reads bytes it did not write as a miss.

See [references/stampede-and-marshallers.md](references/stampede-and-marshallers.md) for the lock
registry's slots and waits, how early recomputation decides, and the marshaller table with key
rotation.

## Testing

- Give the code under test an `ArrayAdapter()` — a real pool, in memory, no cleanup — or a
  `NullAdapter()` to prove it works with every read a miss.
- Lifetimes and early recomputation read the clock in force, so freeze them with `xtr-clock`:

  ```python
  from xtr_cache import ArrayAdapter
  from xtr_clock.testing import mock_time


  async def test_an_invoice_is_cached_for_ten_minutes() -> None:
      cache = ArrayAdapter()
      invoices = Invoices(cache)

      with mock_time("2026-01-01 00:00:00") as clock:
          first = await invoices.get(7)
          assert await invoices.get(7) == first  # a hit; a serialized pool hands back a copy

          clock.sleep(601)
          assert await invoices.get(7) is not first
  ```

- Pass `beta=0` in a test that must not see a value recomputed early.
- With a kernel, override the pool service — a `(type, name)` key for a named pool:
  `await boot_for_test(kernel, overrides={CacheInterface: ArrayAdapter(), (CacheInterface, "sessions"): ArrayAdapter()})`.

## Use in an application

`uv run xtr-recipes recipes:sync` applies the recipe shipped with this package: it lists
`CacheBundle` and ignores `/var/`. That is the steps below a recipe can do; the others it prints
for you to make.

1. **Install** — `uv add "xtr-cache[di]"`; add `redis`, `sodium` or `console` for what you use.
2. **Activate** — `CacheBundle: {"all": True}` in `BUNDLES` in `<app>/bundles.py`, imported from
   `xtr_cache.bundle`.
3. **Brings along** — the logging and console bundles, when those packages are installed. With
   logging, a `cache` channel is added and every pool logs there.
4. **Configure** — optional; with no configuration there is one `app` pool on files:

   ```python
   # <app>/config/cache.py
   from xtr_dependency_injection import configure, env

   from xtr_cache.bundle import CacheConfig, PoolConfig


   @configure
   def cache() -> CacheConfig:
       return CacheConfig(
           app=env("CACHE_DSN"),
           pools={
               "sessions": "redis://cache:6379/1",
               "catalogue": PoolConfig(adapter=["array", "redis://cache:6379"], tags=True),
               "reports": PoolConfig(default_lifetime=3600),  # the app pool's adapter
           },
           stampede_lock="redis://cache:6379/2",
       )
   ```

   | `CacheConfig` field | Meaning |
   | --- | --- |
   | `app` | The `app` pool's adapter, or several to chain. `"filesystem"` by default |
   | `pools` | Every other pool: an adapter, several, or a `PoolConfig(adapter, default_lifetime, tags, namespace)`. No adapter means the `app` pool's. `tags=True` keeps versions in the pool, `tags="other"` in the pool named `other` |
   | `directory` | Where `"filesystem"` writes: `"%kernel.share_dir%/cache"` by default |
   | `prefix_seed` | What each pool's namespace is derived from, with its name: the project directory by default, so two applications on one backend never meet |
   | `stampede_lock` | Any lock DSN; `"flock://%kernel.share_dir%/cache/locks"` by default, `None` for per-process protection only |

5. **Environment** — nothing required; a DSN given as `env(...)` must be set at boot, which
   checks every pool and refuses a DSN no adapter serves.
6. **Ignore** — `var/`, where the filesystem pools write.
7. **Use** — inject the interface; the `app` pool has no qualifier, every other pool is named:

   ```python
   from typing import Annotated

   from xtr_dependency_injection import Target, as_service
   from xtr_cache_contracts import CacheInterface, TagAwareCacheInterface


   @as_service
   class Catalogue:
       def __init__(
           self,
           cache: CacheInterface,  # the app pool
           products: Annotated[TagAwareCacheInterface, Target("catalogue")],
       ) -> None: ...
   ```

   Every pool is registered under `AdapterInterface`, `CacheInterface`,
   `CacheItemPoolInterface` and `NamespacedPoolInterface`, plus `TagAwareCacheInterface` and
   `TagAwareAdapterInterface` when `tags` is set. Replace the pickle marshaller by registering
   your own `MarshallerInterface` service.
8. **Check** — `debug:bundles` shows `cache` as `listed` and `active`.
   `cache:pool:list`, `cache:pool:clear`, `cache:pool:delete`, `cache:pool:invalidate-tags` and
   `cache:pool:prune` are there once the console bundle is active.
9. **Remove** — drop the `BUNDLES` entry, delete `<app>/config/cache.py`, then
   `uv remove xtr-cache`.

Without a container, hand the commands their pools once and import `xtr_cache.command` before the
application runs:

```python
from xtr_cache import CachePoolClearer
from xtr_cache.command import use_pools

use_pools(CachePoolClearer({"app": cache, "sessions": sessions}))
```

## Errors

Every error derives from `CacheError` (the contracts' base). A backend failing is never one of
them: it is logged, and the call misses or returns `False`.

| Error | Raised when |
| --- | --- |
| `InvalidArgumentError` | A key, tag, namespace, `beta`, DSN or option is invalid. Also a `ValueError`; what is wrong is in `reason` |
| `LogicError` | An item of a pool without tags is tagged |
| `MarshallingError` | A marshaller cannot decode stored bytes — pools catch it and read a miss |

## Do not

- Do not check then read then write by hand. Hand `get()` the callback; three calls have a race
  between each.
- Do not treat a `None` return as a miss. `None` is a cached value; use `item.is_hit()`.
- Do not store two types under one key: a hit is returned as the callback's type, unchecked.
- Do not wrap a cache call in `try/except` to survive a dead backend. It already misses and logs.
- Do not mutate what `get()` returned and expect the cache to keep the original — concurrent
  callers get the same object. Copy first.
- Do not put a reserved character in a key; `{}()/\@:` raise `InvalidArgumentError`.
- Do not leave a `RedisAdapter` built by `from_url` unclosed. A namespace is required: without
  one, `clear()` would empty the whole database.
- Do not pickle from a backend others can write to. Use `SodiumMarshaller`.
- Do not sleep in a test to let a value expire. Freeze the clock with `mock_time`.
