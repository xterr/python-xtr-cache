# Adapters

| Adapter | Keeps values | Build it |
| --- | --- | --- |
| `ArrayAdapter` | this process's memory | `ArrayAdapter(60, max_items=1000)` |
| `FilesystemAdapter` | one file each under a directory | `FilesystemAdapter("app", 60, "/var/cache/app")` |
| `RedisAdapter` | a Redis or Valkey server | `RedisAdapter.from_url("redis://cache:6379/0", "app")` |
| `NullAdapter` | nowhere; every read misses | `NullAdapter()` |
| `ChainAdapter` | several pools, fastest first | `ChainAdapter([ArrayAdapter(), redis], 30)` |
| `TagAwareAdapter` | any pool, plus tag versions | `TagAwareAdapter(redis)` |

Shared arguments: `namespace` first positional (`ArrayAdapter` and `ChainAdapter` have no use for
one, so their first argument is `default_lifetime`), then `default_lifetime` in seconds, with `0`
keeping values until they are deleted, and keyword-only `marshaller` and `clock`.

`pool.with_sub_namespace("tenant42")` returns a view of the same pool whose keys live under
`tenant42`, so they clear together and the parent's other keys are left alone.

## `ArrayAdapter`

A dictionary. Values are serialized on the way in by default, so a caller gets a copy it may
change freely; `store_serialized=False` keeps the objects themselves. `max_items` drops the least
recently used beyond a count, `max_lifetime` caps every value's lifetime.

## `FilesystemAdapter`

One file per value under `directory/namespace`. A write lands in a temporary file and replaces the
value's file in one step, so a reader never sees half a value, and the file work runs on a worker
thread. Nothing is created until the first write. An expired file is removed when read;
`await pool.prune()` removes the rest.

Given no directory, the pool uses `xtr-cache` in the system's temporary directory, creates it
readable by its owner alone, and refuses one belonging to another user — reads miss, writes fail,
and the pool logs why. A directory you name is used as it is.

## `RedisAdapter`

```python
from redis.asyncio import Redis
from xtr_cache import RedisAdapter

pool = RedisAdapter(Redis.from_url("redis://cache:6379/0"), "app")  # your client, you close it
pool = RedisAdapter.from_url("redis://cache:6379/0", "app")  # its own client ...
await pool.close()  # ... which it closes
```

Each value is one string key, `namespace:key`, expired by the server. Reads fetch many keys in one
round trip, writes are pipelined, and `clear()` scans the namespace and unlinks in batches — so a
namespace is required: without one, `clear()` would empty the whole database. A client built from a
DSN gives up
on a server silent for 5 seconds unless `?socket_timeout=` and `?socket_connect_timeout=` say
otherwise. One server; not a cluster, not Sentinel. Needs the `redis` extra and a client returning
bytes: one made with `decode_responses=True` raises `InvalidArgumentError`.

## `ChainAdapter`

Reads ask each pool in turn, and a value found in a slower one is copied into the faster ones with
the life it has left, so a copy never outlives the original. Writes, deletes and clears reach
every pool.

## `TagAwareAdapter`

`TagAwareAdapter(items_pool, tags_pool=None, known_tag_versions_ttl=0.15)`. Tag versions live in
`tags_pool`, or in `items_pool` when none is given — a faster or wider-shared pool there makes
invalidation cheaper or wider.

## `AdapterFactory`

`AdapterFactory.create_adapter(connection, namespace, default_lifetime, *, marshaller=None,
directory=None, clock=None)` builds any of them from what a configuration names:

| Given | Adapter |
| --- | --- |
| `"array"`, `"null"` | `ArrayAdapter`, `NullAdapter` |
| `"filesystem"`, `"filesystem:///var/cache/app"` | `FilesystemAdapter`, in the directory given |
| `"redis://…"`, `"rediss://…"`, `"unix://…"`, `"valkey://…"`, `"valkeys://…"` | `RedisAdapter` owning its connection |
| an asyncio Redis client | `RedisAdapter` on that client |

`AdapterFactory.validate(dsn)` refuses a DSN no adapter serves without building one or connecting;
its message names the scheme or the type, never credentials.
