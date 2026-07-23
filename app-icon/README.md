# Watch Next — app icon (B2b)

Square, full-bleed icons — iOS applies its own rounded-corner mask, so do **not**
pre-round these.

## Files
- `appicon-1024.png` — master / App Store size
- `apple-touch-icon.png` (180) — **the one that matters for your Home Screen shortcut**
- `icon-512.png` — PWA / maskable
- `icon-167.png`, `icon-152.png`, `icon-120.png` — iPad / iPhone touch icons
- `favicon-32.png` — browser tab
- `appicon.svg` — editable vector source

## Add the Home Screen icon (single line in your <head>)
```html
<link rel="apple-touch-icon" href="{{ url_for('static', filename='apple-touch-icon.png') }}">
<link rel="icon" type="image/png" sizes="32x32" href="{{ url_for('static', filename='favicon-32.png') }}">
```
Copy the PNGs into your Flask `static/` folder. When you re-add the shortcut on
iPhone (Share → Add to Home Screen) it'll pick up the new icon.
