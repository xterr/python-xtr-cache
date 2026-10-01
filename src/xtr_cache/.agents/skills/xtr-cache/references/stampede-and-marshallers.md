# Stampede protection and marshallers

## Stampede protection

`get()` keeps one hot key from being computed many times over, three ways.

**One computation per key in a process**, always on. Concurrent misses on one key wait for the
first caller and all receive the very object it computed, so copy it before changing it; what was
cached is unaffected. If that computation fails or is cancelled, the others compute for
themselves, side by side.

**One computation per key across processes**, once the pool has a `LockRegistry`:

```python
from xtr_cache import ArrayAdapter, LockRegistry
from xtr_lock import LockFactory, RedisStore

cache = ArrayAdapter()
cache.set_lock_registry(LockRegistry(LockFactory(RedisStore.from_url("redis://cache"))))
```

`LockRegistry(locks, *, slots=20, wait=30, prefix="xtr-cache.")`. Keys are spread over `slots`
locks; the caller that takes a key's slot computes and saves, the others wait `wait` seconds for
it and then read what was saved, or compute for themselves and stop using that slot. The lock
store decides who shares the locks — file locks cover one machine, Redis covers several. Slots are
chosen from the pool's namespace and the key, so two pools never wait on each other's keys.
`set_lock_registry(None)` turns it off again.

**Early recomputation**, tuned by `beta` on each `get()`. A value is stored with how long it took
to compute and when it expires, and a hit may be recomputed before expiry, with a chance that
grows as expiry nears and faster for values that are slow to compute — so one caller refreshes it
while the others keep reading the old one. `0` disables it, `math.inf` recomputes now, `None`
leaves the choice to the pool (`1.0`).

A callback that reads its own key, directly or through what it calls, computes without saving
rather than waiting on itself. Lifetimes and recomputation read the clock in force, so
`xtr_clock.testing.mock_time()` freezes both.

## Marshallers

Adapters that store bytes — files, Redis, and memory while serializing — encode values with a
`MarshallerInterface`. Pickle is the default because a cache reads values back without being told
their type, so a dataclass comes back a dataclass.

| Marshaller | Does |
| --- | --- |
| `DefaultMarshaller()` | `pickle`; anything that pickles round-trips |
| `DeflateMarshaller(inner)` | compresses what `inner` encodes; reads uncompressed bytes too |
| `SodiumMarshaller(keys, inner=None)` | encrypts and authenticates what `inner` encodes |

Unpickling runs code named by the bytes, which is only safe while nothing else can write to the
backend. On a server shared with other applications, encrypt:

```python
from xtr_cache import RedisAdapter, SodiumMarshaller

key = SodiumMarshaller.generate_key()  # once; keep it in a secret, base64-encoded
pool = RedisAdapter.from_url("redis://cache", "app", marshaller=SodiumMarshaller([key]))
```

Bytes anyone else wrote are refused before pickle sees them, and read as a miss. Keys rotate: the
first encrypts, every one decrypts, so put a new key first and keep the old one until what it
encrypted has expired. `SodiumMarshaller.is_supported()` tells whether the `sodium` extra is
installed.
