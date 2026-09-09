# ADR-0003: Close ingress via the security list, never by detaching the public IP

OCI's public-subnet Internet Gateway model requires an instance to hold its own public IP for *outbound* internet as well as inbound — unlike AWS, there is no default SNAT or NAT Gateway equivalent unless one is explicitly built. Detaching the public IP as a hardening step was tried once and killed all outbound connectivity, which broke Tailscale entirely (it could not reach its coordination servers) and required attaching a fresh ephemeral IP to recover.

Deleting the default security list's SSH (port 22) ingress rule reaches the same zero-public-inbound state without touching outbound routing, and does not affect Tailscale either — Tailscale traffic tunnels outside the normal VCN ingress path, so it was never gated by that rule. Building a NAT Gateway would also work, but adds cost and moving parts for no gain here.
