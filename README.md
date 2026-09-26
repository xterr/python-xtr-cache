<div align="center">

# xtr-cache

**Cache pools in memory, in files, in Redis, chained or tag-aware — computed once, even under load.**

<img alt="python 3.11+" src="https://img.shields.io/badge/python-%E2%89%A5%203.11-3776AB?logo=python&logoColor=white">
<img alt="asyncio" src="https://img.shields.io/badge/asyncio-native-1f6feb">
<img alt="typed" src="https://img.shields.io/badge/typed-ty%20%2B%20basedpyright-1f6feb">
<img alt="license MIT" src="https://img.shields.io/badge/license-MIT-blue">

</div>

---

## Why?

A value that is expensive to compute and read often belongs in a cache. Doing that by hand —
check, compute on a miss, save — is three steps with a race between each: under load, every
request that misses computes the same value at the same moment, and the backend it protects takes
the whole stampede at once.

This package implements the [xtr-cache-contracts](../xtr-cache-contracts) interfaces and makes the
backend a constructor argument:

- 🔁 **Fetch-or-compute** — `await cache.get(key, compute)`, one call.
- 🐘 **Stampede protection** — concurrent misses share one computation, across processes too, and
  hot values are refreshed shortly before they expire.
- 🗄️ **Six adapters** — memory, files, Redis, nowhere, a chain of them, or tag-aware on top of any.
- 🏷️ **Tags** — invalidate every value carrying a tag at once, whatever its key.
- 🔐 **Encryption** — values encrypted and authenticated with libsodium, for a shared backend.
- 🧩 **A bundle** — named pools configured in Python, and `cache:pool:*` console commands.

```python
from xtr_cache import FilesystemAdapter, ItemInterface

cache = FilesystemAdapter("app")


async def load_profile(item: ItemInterface) -> Profile:
    item.expires_after(3600)
    return await profiles.fetch(user_id)


profile = await cache.get(f"profile.{user_id}", load_profile)
```

## Install

```sh
uv add xtr-cache
uv add "xtr-cache[redis]"     # RedisAdapter, on redis-py's asyncio client
uv add "xtr-cache[sodium]"    # SodiumMarshaller, on PyNaCl
uv add "xtr-cache[di]"        # the bundle for xtr-dependency-injection
uv add "xtr-cache[console]"   # the cache:pool:* commands for xtr-console
```

Requires Python 3.11+. Depends on `xtr-cache-contracts`, `xtr-clock`, `xtr-lock` and
`xtr-logging-contracts`.

Every contract symbol is re-exported, not redefined: `xtr_cache.CacheInterface is
xtr_cache_contracts.CacheInterface`, so a library typed against the contract receives these pools
unchanged.

## Quick start

Two levels, most code needing the first.

**Fetch-or-compute.** Hand the cache the key and what computes the value; it decides when to call
it. The callback sets the value's lifetime — and tags, on a tag-aware pool — through the item it
receives:

```python
async def load_invoice(item: ItemInterface) -> Invoice:
    item.expires_after(timedelta(minutes=10))
    return await invoices.fetch(invoice_id)


invoice = await cache.get(f"invoice.{invoice_id}", load_invoice)
await cache.delete(f"invoice.{invoice_id}")
```

**Items.** When a hit must be told apart from a miss, several keys read at once, or writes
batched:

```python
item = await cache.get_item("rate.42")
if not item.is_hit():
    await cache.save(item.set(0).expires_after(60))

items = await cache.get_items(["a", "b", "c"])  # every key, hit or miss, in order
await cache.save_deferred(item)  # queued ...
await cache.commit()  # ... stored in one batch
```

Keys are non-empty strings without any of `{}()/\@:`. `None` is a value like any other. A pool
never raises because its backend failed: reads miss, writes return `False`, and the pool logs why
through its logger (`pool.set_logger(...)`).

## Adapters

| Adapter | Keeps values | Shared with | Prunes |
|---|---|---|---|
| `ArrayAdapter` | in this process's memory | nobody | — |
| `FilesystemAdapter` | one file each, under a directory | processes on this machine | ✓ |
| `RedisAdapter` | on a Redis or Valkey server | anything reaching the server | — |
| `NullAdapter` | nowhere: every read misses | — | — |
| `ChainAdapter` | in several pools, fastest first | whatever its pools share | ✓ |
| `TagAwareAdapter` | in any pool, with tag versions | whatever its pools share | ✓ |

Every adapter takes a `default_lifetime` in seconds, applied when an item sets no expiry (`0`
keeps values until deleted), and a `namespace` its keys live under. `pool.with_sub_namespace("t")`
returns a view whose keys live under `t` inside it — cleared together, left alone by the parent's
other keys.

`AdapterFactory.create_adapter(...)` builds any of them from what a configuration names:

| Given | Adapter |
|---|---|
| `"array"`, `"null"` | `ArrayAdapter`, `NullAdapter` |
| `"filesystem"`, `"filesystem:///var/cache/app"` | `FilesystemAdapter`, in the directory given |
| `"redis://…"`, `"rediss://…"`, `"unix://…"`, `"valkey://…"`, `"valkeys://…"` | `RedisAdapter` owning its connection |
| an asyncio Redis client | `RedisAdapter` on that client |

### `ArrayAdapter`

A dictionary. Values are stored serialized by default, so what a caller gets back is a copy it can
change freely; `store_serialized=False` stores the objects themselves. `max_items` drops the least
recently used beyond a count, `max_lifetime` caps every value's lifetime.

### `FilesystemAdapter`

One file per value under `directory/namespace`, holding its expiry, its key and its bytes. A write
goes to a temporary file first and replaces the value's file in one step, so readers never see
half a value. File work runs on a worker thread, off the event loop. Nothing is created until the
first write. An expired file is removed when read; `await pool.prune()` removes the rest.

### `RedisAdapter`

```python
from redis.asyncio import Redis
from xtr_cache import RedisAdapter

pool = RedisAdapter(Redis.from_url("redis://cache:6379/0"), "app")  # your client, you close it
pool = RedisAdapter.from_url("redis://cache:6379/0", "app")  # its own client ...
await pool.aclose()  # ... which it closes
```

Each value is a string key, `namespace:key`, expired by the server itself. Reads fetch many keys
in one round trip, writes are pipelined, and clearing scans the namespace and unlinks its keys in
batches — so set a namespace when the database holds anything else: without one, clearing empties
the database. One server; not a cluster, not Sentinel.

### `ChainAdapter`

```python
cache = ChainAdapter([ArrayAdapter(), RedisAdapter.from_url("redis://cache", "app")])
```

Reads ask each pool in turn. A value found in a slower one is copied into the faster ones, with
the life it has left — every expiring value is stored with its expiry, so a copy never outlives
the original — or `default_lifetime` when it was stored to live forever. Writes, deletes
and clears reach every pool.

### `TagAwareAdapter`

```python
cache = TagAwareAdapter(RedisAdapter.from_url("redis://cache", "app"))


async def load_order(item: ItemInterface) -> Order:
    item.tag([f"customer.{customer_id}", "orders"])
    return await orders.fetch(order_id)


await cache.get(f"order.{order_id}", load_order)
await cache.invalidate_tags([f"customer.{customer_id}"])  # every order of that customer
```

Each tag has a version, kept in the tags pool — the items pool unless another is given. An item is
saved with its tags' versions and is a hit only while every one is unchanged; invalidating a tag
deletes its version. Nothing is listed or scanned, so invalidating costs the same however many
items carry the tag. Versions read are trusted for `known_tag_versions_ttl` seconds (0.15 by
default), which is how soon an invalidation elsewhere reaches this process. Items saved as
deferred take their versions when committed, so an invalidation meanwhile does not apply to them.

Tagging an item of any other pool raises `LogicError`.

## Stampede protection

`get()` protects the backend three ways:

- **One computation per key in a process.** Concurrent misses on one key share the first caller's
  computation. If it fails or is cancelled, the others compute for themselves, side by side.
- **One computation per key across processes**, with a `LockRegistry`. Keys are spread over
  `slots` locks (20 by default); the caller that takes a key's slot computes and saves, the others
  wait for it and read what was saved — or compute themselves after `wait` seconds (30), so a stuck
  holder never stalls every reader, and stop using that slot from then on. Slots are chosen by the
  pool's namespace and the key, so two pools never wait on each other's keys. The lock store decides who shares the locks: file locks for
  every process on a machine, Redis for every machine.

  ```python
  from xtr_lock import LockFactory, RedisStore

  registry = LockRegistry(LockFactory(RedisStore.from_url("redis://cache")))
  cache.set_lock_registry(registry)
  ```

- **Early recomputation.** A computed value is stored with how long it took and when it expires —
  its own lifetime, or the pool's default. On a hit, the value may be recomputed before it
  expires, with a chance that grows as expiry nears and faster for values that are slow to compute. Under load one caller refreshes it while the others
  keep reading the old one, instead of all missing at once. `beta` tunes it: `0` disables it,
  `math.inf` forces a recomputation now.

A callback reading its own key — directly or through what it calls — computes without saving
rather than waiting on itself. Time comes from the clock in force (`xtr_clock`), so
`mock_time()` freezes lifetimes and recomputation alike.

## Marshallers

Adapters that store bytes — files, Redis, and memory when serializing — encode values with a
marshaller, pickle by default: a cache reads values back without being told their type, and pickle
is the format that carries it. A dataclass comes back a dataclass.

| Marshaller | Does |
|---|---|
| `DefaultMarshaller` | `pickle`; any object that pickles round-trips |
| `DeflateMarshaller(inner)` | compresses what `inner` encodes; reads uncompressed bytes too |
| `SodiumMarshaller(keys, inner=None)` | encrypts and authenticates what `inner` encodes |

Unpickling runs code named by the bytes, which is safe only while nothing else can write to the
backend. On a Redis server shared with other applications, use `SodiumMarshaller`: values are
encrypted with libsodium's authenticated secret-key encryption, so they can be neither read nor
forged without a key, and bytes anyone else wrote are refused — read as a miss — before pickle
ever sees them.

```python
from xtr_cache import RedisAdapter, SodiumMarshaller

key = SodiumMarshaller.generate_key()  # once; keep it in a secret, base64-encoded
pool = RedisAdapter.from_url("redis://cache", "app", marshaller=SodiumMarshaller([key]))
```

Keys rotate: the first encrypts, every one decrypts. Put the new key first and keep the old one
until what it encrypted has expired.

## Kernel / bundle

With [xtr-dependency-injection](../xtr-dependency-injection), list the bundle and name the pools:

```python
# app/bundles.py
from xtr_cache.bundle import CacheBundle

BUNDLES = {CacheBundle: {"all": True}}
```

```python
# app/config/cache.py
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

Every pool is registered under `AdapterInterface`, `CacheInterface`, `CacheItemPoolInterface`
and `NamespacedPoolInterface` — plus `TagAwareCacheInterface` and `TagAwareAdapterInterface` for
a pool with `tags=True` — qualified by its name. The `app` pool is also provided without a
qualifier.

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

| `CacheConfig` field | Meaning |
|---|---|
| `app` | The `app` pool's adapter, or several to chain. `"filesystem"` by default |
| `pools` | Every other pool: an adapter, several, or a `PoolConfig(adapter, default_lifetime, tags, namespace)`. A pool without adapter uses `app`'s. `tags=True` keeps tag versions in the pool itself; `tags="other"` keeps them in the pool named `other` |
| `directory` | Where `"filesystem"` keeps files: `"%kernel.share_dir%/cache"` by default, a directory of the system's temporary one set aside for the project |
| `prefix_seed` | What each pool's namespace is derived from, with its name: `"%kernel.project_dir%"` by default, so two applications on one backend never meet; give two the same seed to share values |
| `stampede_lock` | Where stampede locks go — any lock DSN: `"flock://%kernel.share_dir%/cache/locks"` by default, `"redis://…"` to span machines — or `None` for per-process protection only |

An adapter entry is a DSN or keyword `AdapterFactory` reads — `env(...)` included — or a
`Reference(Redis, "cache")` (from `xtr_dependency_injection`) to a client the container already
provides, which the application keeps closing.

- **Zero config**: one `app` pool on files. Nothing is opened until a pool is first asked for.
- **Checked at boot**: booting reads the configuration, `env()` values included, and refuses a DSN
  no adapter serves, a Redis DSN without the `redis` extra, a `Reference` the container
  does not provide, or a stampede lock no store serves — naming the pool, never a DSN's
  credentials.
- **Marshaller**: pools encode with the `MarshallerInterface` service, pickle by default. Register
  your own to replace it:

  ```python
  @as_service
  def marshaller(key: Annotated[str, Autowire(env="CACHE_DECRYPTION_KEY")]) -> MarshallerInterface:
      return SodiumMarshaller([key])
  ```

- **Lifecycle**: between messages the kernel's resetter commits what each pool deferred; when the
  container closes, pools commit and close the connections they opened.
- **Logging**: when the logging bundle is active, a `cache` channel is added and every pool logs
  there — backend failures at warning, stampede waits at info.
- **Console**: when the console bundle is active, the commands below are registered.

## Console commands

| Command | Does |
|---|---|
| `cache:pool:list` | Lists the pools by name |
| `cache:pool:clear POOL… [--all] [--exclude POOL]` | Clears the named pools, or all of them |
| `cache:pool:delete POOL KEY` | Deletes one item |
| `cache:pool:invalidate-tags TAG… [-p POOL]` | Invalidates tags in the named pools, or every tag-aware one |
| `cache:pool:prune` | Removes expired values from every pool that keeps them |

Without a container, hand them pools once, and import `xtr_cache.command` before the application
runs:

```python
from xtr_cache import CachePoolClearer
from xtr_cache.command import use_pools

use_pools(CachePoolClearer({"app": cache, "sessions": sessions}))
```

## Errors

Every error derives from the contract's `CacheError` and carries what went wrong as `reason`. A
backend failing is never one of them: it is logged, and the call misses or returns `False`.

| Error | Raised when |
|---|---|
| `InvalidArgumentError` | A key, tag, namespace, `beta`, DSN or option is invalid (also a `ValueError`) |
| `LogicError` | An item of a pool without tags is tagged |
| `MarshallingError` | A marshaller cannot decode stored bytes — caught by pools, which read a miss |

## Development

Developed in the [python-xtr](https://github.com/xterr/python-xtr) monorepo, under
`packages/xtr-cache`; run the commands below from there. The `python-xtr-cache` repository is a
read-only copy, so send issues and pull requests to the monorepo.

```sh
uv sync
uv run ruff check && uv run ruff format --check && uv run basedpyright && uv run ty check && uv run pytest
```

The suite reaches no server: the Redis adapter runs against a fake client kept in memory, and
every adapter that stores values — all but `NullAdapter`, which stores none — passes the same
conformance tests.

## License

MIT — see [LICENSE](LICENSE).
