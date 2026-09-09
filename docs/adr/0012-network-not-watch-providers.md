# ADR-0012: The platform on a card is TMDB's network, not its watch providers

Each card names the platform its show airs on — "HBO", "Apple TV+", "Hulu". Nothing in Yamtrack's database records one. So it is a TMDB lookup, like episode titles.

TMDB answers two different questions here. `GET /3/tv/{id}` carries `networks[]` — who *made and aired* the show. `GET /3/tv/{id}/watch/providers` carries where it can be streamed *right now, in a given country*, which is a licensing fact: it is keyed by region, it changes when a deal lapses, and one show returns a different answer per viewer. The network is the one that belongs on a card that says "this aired, you haven't watched it", and it is region-free, so it needs no country configured and cannot go stale under a running container. It already covers the cases that prompted this: Apple TV+ and Hulu are TMDB *networks* for their own originals, not merely places to stream them.

A show can list several networks (a co-production). The first named one is shown; TMDB orders them with the primary first.

Because the answer cannot drift the way a mid-run season's episode list does, the network lookup deliberately carries none of the re-fetch machinery [ADR-0010](0010-refetch-on-miss-not-on-a-timer.md) builds for titles: one answered lookup per show holds for the life of the process, "no network at all" included. Only a failure that left the answer unknown — a timeout, a 429, a 200 in an unexpected shape — is retried, on the next render.
