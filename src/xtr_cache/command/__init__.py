"""The ``cache:pool:*`` console commands.

Importing this module declares them. With a container, the cache bundle loads
it when the console bundle is active, and every command acts on the pools the
bundle registered. Without one, give them pools with :func:`use_pools`:

```python
from xtr_cache import CachePoolClearer, FilesystemAdapter
from xtr_cache.command import use_pools

use_pools(CachePoolClearer({"app": FilesystemAdapter("app")}))
```

Needs the ``console`` extra: ``xtr-cache[console]``.
"""

from __future__ import annotations

from .cache_pool_clear_command import CachePoolClearCommand
from .cache_pool_delete_command import CachePoolDeleteCommand
from .cache_pool_invalidate_tags_command import CachePoolInvalidateTagsCommand
from .cache_pool_list_command import CachePoolListCommand
from .cache_pool_prune_command import CachePoolPruneCommand
from .pools import use_pools

__all__ = [
    "CachePoolClearCommand",
    "CachePoolDeleteCommand",
    "CachePoolInvalidateTagsCommand",
    "CachePoolListCommand",
    "CachePoolPruneCommand",
    "use_pools",
]
