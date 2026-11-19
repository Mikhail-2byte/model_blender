"""Draw the original, shared QC/crack atlas with Pillow (512 × 256 RGBA)."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
SCALE = 4
SIZE = (512, 256)
FONT = Path("C:/Windows/Fonts/arialbd.ttf")


def scaled(points):
    return [(round(x * SCALE), round(y * SCALE)) for x, y in points]


def line(draw, points, fill, width):
    draw.line(scaled(points), fill=fill, width=round(width * SCALE), joint="curve")


def main():
    # The stamp occupies the left half, with two crack inks stacked at right.
    canvas = Image.new("RGBA", tuple(n * SCALE for n in SIZE))
    draw = ImageDraw.Draw(canvas)
    ink = (36, 99, 65, 245)
    outline = [(42, 39), (212, 39), (232, 58), (232, 197), (212, 216),
               (42, 216), (23, 197), (23, 58), (42, 39)]
    line(draw, outline, ink, 8)
    line(draw, [(44, 156), (211, 156)], ink, 4)
    for string, center, size in [("ОТК", (104, 105), 61), ("ПРОЙДЕНО", (128, 182), 25)]:
        draw.text(scaled([center])[0], string, fill=ink, anchor="mm",
                  font=ImageFont.truetype(str(FONT), size * SCALE))
    line(draw, [(176, 115), (187, 127), (208, 97)], ink, 9)

    main_crack = [(23, 48), (55, 58), (86, 43), (105, 60), (121, 62),
                  (146, 82), (170, 68), (193, 76), (231, 62)]
    branches = [[(105, 60), (113, 33), (143, 18)], [(86, 43), (64, 27), (67, 13)],
                [(146, 82), (132, 97), (133, 117)], [(193, 76), (204, 95), (219, 105)]]
    for top, stroke, edge in [(0, (24, 23, 37, 255), (247, 241, 250, 210)),
                              (128, (19, 18, 28, 255), (175, 157, 174, 210))]:
        for index, segment in enumerate([main_crack, *branches]):
            points = [(x + 256, y + top) for x, y in segment]
            line(draw, [(x, y + 2) for x, y in points], edge, 7 if index == 0 else 4)
            line(draw, points, stroke, 5 if index == 0 else 2.5)

    canvas.resize(SIZE, Image.Resampling.LANCZOS).save(HERE / "T_DroneQuad_Decals.png")


if __name__ == "__main__":
    main()
