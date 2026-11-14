# Biverse website

A static site (no build step). Deployed with Vercel.

## Deploy on Vercel

1. Import the `CeoFred/biverse` repository in Vercel.
2. Set **Root Directory** to `website`. Leave Framework Preset as **Other**; there is no build
   command. `vercel.json` sets clean URLs and security and cache headers.
3. Deploy. After adding a custom domain, change the `og:image` URL in `index.html` to an absolute
   URL on that domain (some social sites ignore relative image URLs).

Or from this folder: `npx vercel` (preview) and `npx vercel --prod`.

## Local preview

```bash
python3 -m http.server 8080 --directory website
```

## Keeping it current

- `data-version` on `<html>` in `index.html` must match `biverse.__version__`. Download buttons
  link straight to `releases/download/v<version>/…`; a test checks the two match.
- Icons and logos come from `python tools/make_icons.py`. The social image comes from
  `python3 tools/make_og_image.py` (needs Pillow). Screenshots are WebP copies of
  `docs/screenshots/`.
