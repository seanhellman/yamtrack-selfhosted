# ADR-0002: Host on Oracle Always Free, reached only via Tailscale

The stack runs on an Oracle Cloud "Always Free" ARM VM rather than on the Mac that first hosted it, self-owned hardware, or a paid VPS. It is the only one of those that gives always-on access from anywhere at $0/month, and Tailscale supplies the access path, so the instance needs no public inbound exposure at all.

The accepted cost is dependence on Oracle continuing to offer the tier, plus the account-level care that requires (Pay-As-You-Go conversion to escape idle-instance reclamation, a budget alert as a spend tripwire). Buying a refurb mini-PC remains possible but has no remaining justification beyond wanting to own the hardware, since remote access is already solved at no cost.

The Mac that hosted the stack LAN-only until 2026-07-07 was stopped once its data reached the instance, and is not run going forward.

## Consequences

Provisioning is fiddly in ways the console does not warn about. These bit once each during setup on 2026-07-07 and would bite again on a rebuild:

- **Pick the aarch64-suffixed image.** The plain build of the same Ubuntu version is amd64 and `VM.Standard.A1.Flex` rejects it — "shape not compatible with image".
- **The full 2 OCPU / 12 GB allocation is behind the "Change shape" panel.** The Flex shape defaults to 1 OCPU / 6 GB, and the sliders that reach the free ceiling are not on the main create-instance form.
- **"Automatically assign public IPv4 address" can stick off**, even with a public subnet selected — a console state bug. Create the instance anyway, then attach one via Instance → Networking → VNIC → IP Addresses → Edit → Public IP Type → Ephemeral Public IP.
- **"View estimated cost" shows ~$2/month and is wrong.** It prices the boot volume at list rate without netting out the Always Free block storage allowance. Cost Analysis reports it correctly.

Keeping the instance is likewise fiddly: the public IP that setup attaches is also the *outbound* path, so it must stay attached — see [ADR-0003](0003-close-ingress-not-the-public-ip.md). If Tailscale and SSH ever go down together, OCI's Instance Console Connection is a genuine network-independent way back in; it is not set up, and enabling it needs its own one-time SSH key upload.
