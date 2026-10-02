"""Build the web assets for the gift pack from the Claude Design masters.

Masters: C:/work/lottosonline-rebuild/design/pack-handover/lottos-gift-pack/png-masters
         (12 layers per finish, 1200 x 1600 RGBA, every layer on the full canvas).
Output:  static/brands/lottosonline/img/packs/ as WebP, plus geometry.json.

Run again whenever the masters change:  python site/tools/pack_assets.py

Two things this script does that matter:

* **Every layer keeps the full canvas.** The pack front and the tear strip are cut from
  one artwork along one 116-point tear line, and the two torn-edge layers are built on
  that same line. Crop any of them to its own content and nothing stacks any more.
* **Layers identical in both finishes are written once**, into ``shared/``. Only four
  layers actually differ (pack back, pack front, tear strip, card back), so a visitor
  loads one finish at roughly 150 KB instead of both at 230 KB. The hero card is
  deliberately among the shared ones: premium must never look like a better gift.

The four soft layers ship at half or quarter resolution and are drawn at full size. They
are smooth gradients, so nothing is visible, and it is most of the saving.

**Claude Design's own WebP is used where it exists**, because it is better than anything
this script produces: their encoder beats Pillow by a third on the sparkle and the card
back, and re-encoding would cost bytes for nothing. Generating from the PNG masters is
the fallback for a layer they have not shipped, so new artwork still works on its own.
"""
import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "design" / "pack-handover" / "lottos-gift-pack"
MASTERS = SRC / "png-masters"
OUT = Path(__file__).resolve().parents[1] / "static" / "brands" / "lottosonline" / "img" / "packs"

FINISHES = ("standard", "premium")

#: layer -> (output size, quality). Anything absent ships at the full 1200 x 1600.
PROFILE = {
    "01-shadow": ((600, 800), 80),
    "07-pack-interior": ((600, 800), 80),
    "10-foil-sheen": ((300, 400), 82),
    "11-glow": ((300, 400), 82),
    "09-card-hero": (None, 86),
    "12-sparkle": (None, 88),
}
DEFAULT = (None, 82)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _webp(src: Path, dst: Path, size, quality: int) -> int:
    im = Image.open(src).convert("RGBA")
    if size:
        im = im.resize(size, Image.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "WEBP", quality=quality, method=6)
    return dst.stat().st_size


def build() -> None:
    if not MASTERS.is_dir():
        raise SystemExit("masters not found: %s" % MASTERS)

    layers = sorted(p.stem for p in (MASTERS / "standard").glob("*.png"))

    # Which layers are byte-identical across the finishes? Those go in shared/.
    shared = [n for n in layers
              if _digest(MASTERS / "standard" / f"{n}.png") == _digest(MASTERS / "premium" / f"{n}.png")]
    differs = [n for n in layers if n not in shared]

    if OUT.exists():
        shutil.rmtree(OUT)

    totals = {"shared": 0, "standard": 0, "premium": 0}
    regenerated = []

    def emit(bucket: str, master_finish: str, name: str) -> None:
        """Their WebP if they shipped it, otherwise ours from the master."""
        dst = OUT / bucket / f"{name}.webp"
        shipped = SRC / "webp-production" / f"{bucket}-{name}.webp"
        if shipped.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(shipped, dst)
        else:
            size, q = PROFILE.get(name, DEFAULT)
            _webp(MASTERS / master_finish / f"{name}.png", dst, size, q)
            regenerated.append(f"{bucket}/{name}")
        totals[bucket] += dst.stat().st_size

    for name in shared:
        emit("shared", "standard", name)
    for finish in FINISHES:
        for name in differs:
            emit(finish, finish, name)

    # The tear line, pack bounds and crimp positions the animation needs.
    shutil.copyfile(SRC / "webp-production" / "geometry.json", OUT / "geometry.json")

    for f in sorted(OUT.rglob("*")):
        if f.is_file():
            print("   %-40s %6.1f KB" % (str(f.relative_to(OUT)).replace("\\", "/"),
                                         f.stat().st_size / 1024))

    print()
    print("   shared in both finishes : %s" % ", ".join(shared))
    print("   differs per finish      : %s" % ", ".join(differs))
    print("   regenerated from PNG    : %s" % (", ".join(regenerated) or "none, all shipped as WebP"))
    print()
    for finish in FINISHES:
        kb = (totals["shared"] + totals[finish]) / 1024
        print("   a visitor loading %-8s : %6.1f KB" % (finish, kb))
    print("   everything on disk       : %6.1f KB"
          % (sum(totals.values()) / 1024))


if __name__ == "__main__":
    build()
