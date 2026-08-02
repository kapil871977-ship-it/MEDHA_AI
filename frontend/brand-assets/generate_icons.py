"""
Generate every branded image the app ships, from one source logo.

Source : brand-assets/fortune-guru-logo-original.png (2816x1536, ~6.4 MB)
Outputs:
  public/fortune-guru-logo.png   web-sized logo used for avatars (was 6.4 MB)
  public/logo192.png             PWA icon      (replaces the CRA React default)
  public/logo512.png             PWA icon      (replaces the CRA React default)
  public/maskable-192.png        PWA maskable icon (80% safe zone)
  public/maskable-512.png        PWA maskable icon (80% safe zone)
  public/favicon.ico             multi-size favicon
  assets/icon.png                1024x1024 source for `npx capacitor-assets generate`
  assets/icon-foreground.png     Android adaptive-icon foreground
  assets/icon-background.png     Android adaptive-icon background
  assets/splash.png              2732x2732 light splash
  assets/splash-dark.png         2732x2732 dark splash

Run from the frontend/ directory:
    python brand-assets/generate_icons.py
"""
import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND = os.path.dirname(HERE)
PUBLIC = os.path.join(FRONTEND, "public")
ASSETS = os.path.join(FRONTEND, "assets")

SOURCE = os.path.join(HERE, "fortune-guru-logo-original.png")
BG = (2, 6, 23, 255)          # #020617 — matches capacitor backgroundColor


def _load_source():
    img = Image.open(SOURCE).convert("RGBA")
    return img.crop(img.getbbox() or (0, 0, *img.size))


def _centered(logo, canvas_size, coverage, background=BG):
    """Fit `logo` inside a square canvas, occupying `coverage` of its width."""
    canvas = Image.new("RGBA", (canvas_size, canvas_size), background)
    target = int(canvas_size * coverage)
    scale = min(target / logo.width, target / logo.height)
    resized = logo.resize(
        (max(1, int(logo.width * scale)), max(1, int(logo.height * scale))),
        Image.LANCZOS,
    )
    canvas.paste(
        resized,
        ((canvas_size - resized.width) // 2, (canvas_size - resized.height) // 2),
        resized,
    )
    return canvas


def main():
    os.makedirs(ASSETS, exist_ok=True)
    logo = _load_source()
    print(f"source: {logo.size}")

    # Web logo — the app renders this at 88-120 px, so 512 px covers even a
    # 4x-DPI screen. The original stays in brand-assets/ for future re-exports.
    web = logo.copy()
    web.thumbnail((512, 512), Image.LANCZOS)
    web.save(os.path.join(PUBLIC, "fortune-guru-logo.png"), optimize=True)

    # Standard PWA / launcher icons.
    for size in (192, 512):
        _centered(logo, size, 0.86).save(
            os.path.join(PUBLIC, f"logo{size}.png"), optimize=True
        )
        # Maskable icons need the artwork inside the inner 80% safe zone.
        _centered(logo, size, 0.62).save(
            os.path.join(PUBLIC, f"maskable-{size}.png"), optimize=True
        )

    _centered(logo, 256, 0.86).save(
        os.path.join(PUBLIC, "favicon.ico"),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    # Native sources consumed by `npx capacitor-assets generate`.
    _centered(logo, 1024, 0.80).save(os.path.join(ASSETS, "icon.png"), optimize=True)
    _centered(logo, 1024, 0.60, background=(0, 0, 0, 0)).save(
        os.path.join(ASSETS, "icon-foreground.png"), optimize=True
    )
    Image.new("RGBA", (1024, 1024), BG).save(
        os.path.join(ASSETS, "icon-background.png"), optimize=True
    )
    splash = _centered(logo, 2732, 0.34)
    splash.save(os.path.join(ASSETS, "splash.png"), optimize=True)
    splash.save(os.path.join(ASSETS, "splash-dark.png"), optimize=True)

    print("\nGenerated:")
    for path in (
        os.path.join(PUBLIC, "fortune-guru-logo.png"),
        os.path.join(PUBLIC, "logo192.png"),
        os.path.join(PUBLIC, "logo512.png"),
        os.path.join(PUBLIC, "maskable-192.png"),
        os.path.join(PUBLIC, "maskable-512.png"),
        os.path.join(PUBLIC, "favicon.ico"),
        os.path.join(ASSETS, "icon.png"),
        os.path.join(ASSETS, "icon-foreground.png"),
        os.path.join(ASSETS, "icon-background.png"),
        os.path.join(ASSETS, "splash.png"),
        os.path.join(ASSETS, "splash-dark.png"),
    ):
        print(f"  {os.path.relpath(path, FRONTEND):34s} {os.path.getsize(path) / 1024:8.1f} KB")


if __name__ == "__main__":
    main()
