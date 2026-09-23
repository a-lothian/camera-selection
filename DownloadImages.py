# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow", "requests"]
# ///
"""Download camera thumbnails listed in camera_image_urls.json.

For each entry, fetches `image_url` (or, if it's null, scrapes the product
page's og:image), turns flat white backgrounds transparent, trims the empty
margin, saves assets/<id>.png and sets that camera's "image" in cameras.json.
Also fills in each camera's "link" from `product_page` if it doesn't have one.

    uv run DownloadImages.py            # skip cameras that already have a thumbnail
    uv run DownloadImages.py --force    # re-download everything
"""

from __future__ import annotations

import argparse
import html
import io
import json
import re
import sys
from urllib.parse import urljoin

import requests
from PIL import Image, ImageChops, ImageDraw

from CameraInput import ASSETS_DIR, DATA_FILE, ROOT, load_cameras, make_thumbnail

URLS_FILE = ROOT / "camera_image_urls.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/png,image/*,text/html;q=0.9,*/*;q=0.8",
}


def find_image_on_page(page_url: str, session: requests.Session) -> str | None:
    """Find a product image URL in a product page's HTML."""
    r = session.get(page_url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    text = r.text
    # Nikon pages list many accessories; prefer a render whose name has this product's number.
    pid = re.search(r"/p/[^/]+/(\d+)/", page_url)
    if pid:
        m = re.search(rf"https://images\.cdn\.[^\"'\s)]+/(?:FrontLeft-)?{pid.group(1)}-[^\"'\s)]+\.png", text)
        if m:
            return html.unescape(m.group(0))
    for pattern in (
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
    ):
        m = re.search(pattern, text, re.I)
        if m:
            return urljoin(page_url, html.unescape(m.group(1)))
    return None


def clean_background(img: Image.Image, tolerance: int = 18) -> Image.Image:
    """Make an edge-connected flat white background transparent, then crop to content."""
    img = img.convert("RGBA")
    alpha = img.getchannel("A")
    has_transparency = alpha.getextrema()[0] < 250

    if not has_transparency:
        # Flood-fill near-white from every edge pixel into a marker colour.
        rgb = img.convert("RGB")
        w, h = rgb.size
        marker = (255, 0, 255)
        edge = [(x, 0) for x in range(0, w, 8)] + [(x, h - 1) for x in range(0, w, 8)]
        edge += [(0, y) for y in range(0, h, 8)] + [(w - 1, y) for y in range(0, h, 8)]
        for xy in edge:
            px = rgb.getpixel(xy)
            if px != marker and min(px) >= 255 - tolerance:
                ImageDraw.floodfill(rgb, xy, marker, thresh=tolerance)
        diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, marker))
        r, g, b = diff.split()
        mask = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v else 0)
        # Only trust it if a meaningful share of the image was background.
        if mask.histogram()[0] > 0.1 * w * h:
            img.putalpha(mask)

    bbox = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if bbox:
        pad = max(4, int(0.03 * max(bbox[2] - bbox[0], bbox[3] - bbox[1])))
        bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(img.width, bbox[2] + pad), min(img.height, bbox[3] + pad))
        img = img.crop(bbox)
    return img


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="re-download images that already exist")
    args = parser.parse_args()

    entries = json.loads(URLS_FILE.read_text(encoding="utf-8"))["cameras"]
    cameras = load_cameras()
    by_id = {c["id"]: c for c in cameras}
    session = requests.Session()
    ok, failed = 0, []

    for entry in entries:
        cid = entry["id"]
        cam = by_id.get(cid)
        if cam is None:
            print(f"  skip  {cid}: not in cameras.json")
            continue
        if entry.get("product_page") and not cam.get("link"):
            cam["link"] = entry["product_page"]
        dest = ASSETS_DIR / f"{cid}.png"
        if dest.exists() and not args.force:
            cam["image"] = f"assets/{dest.name}"
            print(f"  have  {cid}")
            ok += 1
            continue
        try:
            url = entry.get("image_url") or find_image_on_page(entry["product_page"], session)
            if not url:
                raise RuntimeError("no image found on product page")
            r = session.get(url, headers=HEADERS, timeout=60)
            if not r.ok and entry.get("image_url") and entry.get("product_page"):
                # Listed URL is dead or blocked; try the product page instead.
                url = find_image_on_page(entry["product_page"], session) or url
                r = session.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            with Image.open(io.BytesIO(r.content)) as src:
                img = clean_background(src)
            tmp = io.BytesIO()
            img.save(tmp, "PNG")
            make_thumbnail(tmp, dest)
            cam["image"] = f"assets/{dest.name}"
            print(f"  saved {cid}  ({img.width}x{img.height} from {url[:70]}…)")
            ok += 1
        except Exception as exc:  # noqa: BLE001 — report and carry on with the rest
            failed.append(cid)
            print(f"  FAIL  {cid}: {exc}")

    # Write back in the existing order (CameraInput's save_cameras would re-sort).
    DATA_FILE.write_text(json.dumps({"cameras": cameras}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n{ok} with images, {len(failed)} failed{': ' + ', '.join(failed) if failed else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
