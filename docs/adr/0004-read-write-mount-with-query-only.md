# ADR-0004: Read the WAL database through a read/write mount plus `PRAGMA query_only`

Yamtrack's SQLite database runs in WAL mode, and a WAL reader must be able to update the `-shm` wal-index. A `:ro` bind mount or a `mode=ro` connection therefore cannot read it reliably: `mode=ro` only works while the `-wal` file is empty, so it fails intermittently and silently misses uncheckpointed writes.

Watch Next instead mounts `./db` read/write, runs as uid/gid 1000 (the DB files' owner, so it can touch the sidecars), and enforces read-only-ness in-process with `PRAGMA query_only = ON`, which rejects any write with `SQLITE_READONLY`. The read-only guarantee moves from the filesystem to the engine, which is the only layer that can give it here.
