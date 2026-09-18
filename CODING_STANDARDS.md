# Coding standards

Conventions for writing code in this repo. Each rule carries the shortest reason that would stop someone deleting it; the longer arguments live in `docs/adr/`.

## `watchnext/templates/watch_next.html`, `watchnext/static/`

### CSS

- **Gate every `:hover` rule behind `@media (hover: hover)`.** iOS latches `:hover` onto the last-tapped element until you tap elsewhere, which leaves the mark-watched button stuck looking checked. Touch feedback comes from `:active` and the `.marking` class instead.
- **Toasts render into the fixed-position `#toasts` overlay, outside `<main>`.** In normal flow they push the whole list down on every mark.
- **Error toasts get an explicit `×`; success toasts do not.** Errors persist, so they need a dismiss; a close button on a self-dismissing message is noise. Every toast is also tap-to-dismiss.
- **Keep the `color-scheme: dark` meta tag before the stylesheet, and the background colour on `html`.** Without both, WebKit paints its first canvas white, which reads as a flutter when handing off from the same-coloured launch splash.

### Markup

- **Posters are not `loading="lazy"`.** The list is short and every poster is in the viewport, so lazy loading only delays the first complete paint.
- **Every `.card` carries `data-key="<media_id>|<season_number>"`.** It is how the client finds the card to patch.
- **The badge is styled off `data-badge`, never a class.** `SERIES FINALE` has a space in it, so as a class attribute it would split into two tokens and get its tint by accident.
- **Always emit `.epname`, `.code`, `.more`, `.platform`, and `.badge`, blank when unused.** `:empty { display: none }` hides them, so the client only ever sets `textContent` and never creates elements.
- **Do not remove `apple-mobile-web-app-capable=yes` or the `apple-touch-startup-image` links.** That meta tag is the legacy gate that lets iOS honor the startup image — it no longer controls display mode, so it looks removable and is not. See [ADR-0007](docs/adr/0007-exact-per-device-startup-images.md).

### JavaScript

- **Card markup lives only in the Jinja template, never in JS.** The template stays the single source of card HTML.
- **When a change cannot be patched in place, fall back to `location.reload()`** — a genuinely new row, an emptied list, or a failed request. This is what keeps the rule above possible.
- **Never break the no-JS path.** The form must still post normally, with the view doing Post/Redirect/Get and a server-rendered flash.
- **Keep the pull-to-refresh spinner's `MIN_SPIN_MS` floor.** The response is usually fast enough that an honest spinner reads as a flicker rather than a refresh; the minimum spin is deliberate, not a stall.
- **Mark-watched confirms before the row leaves.** The card takes `.marking` on tap and only exits via `.leaving` once the response says it is gone; on failure `.marking` is removed, the button re-enables, and an error toast is raised. Do not make the exit optimistic — a row that leaves and comes back is worse than one that waits.

## `watchnext/*.py`

- **External lookups are best-effort and never raise.** Any failure — no token, network error, rate limit, 404 — returns `None` and the caller degrades (a `SxxExx` label instead of a title, no platform line instead of one). A lookup must never break the page.
- **Record what the service answered, never a transient failure.** A 404 is recorded; a timeout, a 429 or a 200 in an unexpected shape is not, so it retries on the next render rather than being held off.
- **A settled lookup is never repeated, and a miss is what re-fetches.** Nothing expires on a timer: a resolved answer costs no further requests, and an unsettled one (absent, unnamed, or a name that may still improve) is re-checked no more often than `_REFETCH_FLOOR`, tracked per episode. Deleting that tracking to simplify the code silently reintroduces stale titles — the floor is what makes re-fetching safe, not an optimisation on top of it. → [ADR-0010](docs/adr/0010-refetch-on-miss-not-on-a-timer.md)
- **That re-fetching is the episode lookup's alone.** A show's own facts — its network, its status, the episode that aired last — are answered once and never re-checked. The network can't grow underneath us the way a mid-run season's episode list does; `status` can, and is cached anyway — a show that ends mid-process reads `FINALE` until the next restart, which is what no token at all does too. → [ADR-0012](docs/adr/0012-network-not-watch-providers.md)
- **`SERIES FINALE` compares against `last_episode_to_air`, never against a season count.** Rebuilding it as arithmetic over `number_of_seasons` reintroduces a dependency on the season response, which can only withhold the badge. Unlike `FINALE` it deliberately doesn't also require `episode_type`.
- **Database access is SELECT-only, under `PRAGMA query_only = ON`.** Writes go over HTTP to Yamtrack's own endpoints. See [ADR-0004](docs/adr/0004-read-write-mount-with-query-only.md) and [ADR-0005](docs/adr/0005-mark-watched-via-episode-save.md).
- **A mark is not reported watched until the query says the episode left the list.** `episode_save` answers 200 on a redirect to the login page, so the HTTP response alone can't tell a save from a bounce — an expired session once reported success for a week of marks that saved nothing. `_unconfirmed()` re-queries and fails the request when the episode is still outstanding; deleting it as a redundant read restores a silent failure.

## `docker-compose.yml`

- **Pin the image to an explicit version, never `latest`.**
- **`SECRET` comes from `env_file`; everything this deployment sets on every run is inlined under `environment:`.** Upstream's compose inlines `SECRET`; this repo deviates deliberately to keep it out of the tracked file. The rest — `TZ`, `REDIS_URL`, `REGISTRATION` — is committed, so it cannot drift from an untracked `.env` and needs no copy in `.env.example`. → [ADR-0014](docs/adr/0014-registration-closed-in-compose.md)
- **Do not change the `./db` mount to `:ro`.** It will silently break WAL reads — see [ADR-0004](docs/adr/0004-read-write-mount-with-query-only.md).
