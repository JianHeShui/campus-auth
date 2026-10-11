"""生成托盘图标：白底黑「水」字，多尺寸 ICO。

用超采样（4x 渲染 + LANCZOS 缩小）提升清晰度，边缘更平滑。
用 bundled 运行时里的 Pillow 运行：python make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "tray.ico"

FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyhbd.ttc",   # 微软雅黑粗体（优先，现代清晰）
    "C:/Windows/Fonts/simhei.ttf",   # 黑体（笔画粗，小尺寸清晰）
    "C:/Windows/Fonts/msyh.ttc",     # 微软雅黑
    "C:/Windows/Fonts/simsun.ttc",   # 宋体
]


def find_font() -> str | None:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def make_icon() -> None:
    font_path = find_font()
    if not font_path:
        raise SystemExit("未找到中文字体，无法生成图标")

    sizes = [16, 24, 32, 48, 64, 128, 256]

    # 超采样：先在 4x 尺寸（1024）渲染「水」字，再缩小到各尺寸，边缘抗锯齿更平滑
    supersample = 4
    master = 256 * supersample  # 1024
    master_img = Image.new("RGBA", (master, master), (255, 255, 255, 255))  # 白底不透明
    draw = ImageDraw.Draw(master_img)
    font = ImageFont.truetype(font_path, int(master * 0.80))
    bbox = draw.textbbox((0, 0), "水", font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (master - w) / 2 - bbox[0]
    y = (master - h) / 2 - bbox[1]
    draw.text((x, y), "水", fill=(0, 0, 0, 255), font=font)  # 黑字

    images = []
    for size in sizes:
        images.append(master_img.resize((size, size), Image.LANCZOS))

    images[0].save(OUT, format="ICO", sizes=[(s, s) for s in sizes], append_images=images[1:])
    print(f"已生成图标: {OUT}  字体: {font_path}  尺寸: {', '.join(map(str, sizes))}")


if __name__ == "__main__":
    make_icon()


if __name__ == "__main__":
    make_icon()
