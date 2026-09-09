# ADR-0007: Exact per-device `apple-touch-startup-image` files for the launch splash

Three ways of replacing the white iOS launch flash with a solid `#212529` splash were tested in order, on a real device:

1. **Web app manifest `background_color`** — ignored by iOS. Still flashed white. (The manifest is retained anyway, for name, icons, and display metadata.)
2. **One solid startup image with a loose or absent `media` query** — ignored. This was a deliberate test of whether iOS would accept a non-exact match given that the image is a solid colour. It will not.
3. **Exact per-device `apple-touch-startup-image`** — works.

iOS only uses a startup image whose `media` query exactly matches the device (`device-width` and `device-height` in CSS px, `-webkit-device-pixel-ratio`, orientation) and whose file is generated at that exact pixel resolution.

## Consequences

Because the `media` query *is* the selection mechanism, there is no "use the device's own size" directive, so the list cannot be made universal and is not future-proof: an iPhone whose resolution is not listed silently falls back to a white flash. There is no live Apple API for device resolutions either — tools such as `pwa-asset-generator` bundle a static list that lags new hardware.

Test 2 above did not isolate *why* it failed: that image had both a loose query and dimensions that did not match the test device. The conclusion is unchanged either way, since each resolution still needs its own `<link>`.
