# ADR-0014: Registration is closed in the tracked compose file

Yamtrack defaults `REGISTRATION` to `True`. This deployment runs it closed. The instance takes no public inbound, so an open sign-up page reaches nobody today — it would be a hole after any widening of that posture, and closing it costs nothing.

`REGISTRATION=False` is the same on every run of this compose file, so it is inlined under `environment:` alongside `REDIS_URL`. The alternative was a matching line in the committed `.env.example`. That was rejected: drift between the template and the instance's `.env` was the reason for touching this at all, and a second copy is what drifts. Committing the value deletes the copy instead, and `.env` goes back to holding only `SECRET`.

Closing sign-up leaves no browser route to the first user, and `ADMIN_ENABLED` defaults to `False`. Opening registration, creating the account and closing it again was rejected because it fails unsafe: forget the last step and the deployment sits in the state the setting exists to prevent, with nothing to surface it. `manage.py createsuperuser` never opens sign-up at all. With the admin disabled the superuser flags are inert.

Run that command as `abc`, the uid-1000 account the app runs as. The image sets no `USER`, so `docker compose exec` otherwise writes the database as root and leaves root-owned `-wal`/`-shm` sidecars that neither Yamtrack nor Watch Next can write. → [ADR-0004](0004-read-write-mount-with-query-only.md)
