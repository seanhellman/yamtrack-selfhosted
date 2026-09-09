# ADR-0006: No service-worker cached shell for Watch Next

Cold launch of Watch Next from the iOS Home Screen takes 3-4 seconds. Measurement ruled the application out: server response over a warm Tailscale connection is ~190ms and the page is 16 KB with no render-blocking external files. The delay is iOS evicting the web app from memory (forcing a cold WebKit process per launch) plus Tailscale re-handshaking its tunnel after idle — neither fixable from application code.

A service-worker cached shell was the obvious remedy and was rejected. It is HTTPS-only, so it would need Tailscale HTTPS certificates — which publish the hostname to public Certificate Transparency logs — plus `tailscale serve`. The deciding objection is that a cacheable shell must be data-free, which forces the page from server-rendered cards to client-rendered ones, duplicates the card markup in JavaScript, and weakens the no-JS path. Roughly 2 seconds of cold launch does not buy that.
