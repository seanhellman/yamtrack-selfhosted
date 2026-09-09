# ADR-0001: SQLite over Postgres

Yamtrack supports both; this deployment uses SQLite, bind-mounted as a plain directory. That makes backup and migration a matter of copying a folder rather than operating a second database server — the property that matters most for a deployment expected to move between hosts. The cost is concurrent-writer robustness, which a single-user tracker does not need. Redis is still required regardless, as broker and cache.
