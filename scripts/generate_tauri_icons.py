"""
生成 Tauri 应用图标
使用 PIL 创建一个渐变背景 + "盐" 字样的图标
"""

import os
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "src-tauri", "icons")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def make_gradient_bg(size: int) -> Image.Image:
    """创建蓝紫渐变背景"""
    img = Image.new("RGB", (size, size), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 对角线渐变
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            r = int(56 + (123 - 56) * t)  # 56 -> 123
            g = int(132 + (97 - 132) * t)  # 132 -> 97
            b = int(255 + (255 - 255) * t)  # 255
            draw.point((x, y), fill=(r, g, b))
    return img


def draw_icon(size: int) -> Image.Image:
    """绘制一个圆角图标"""
    img = make_gradient_bg(size)
    mask = Image.new("L", (size, size), 0)
    md = ImageDraw.Draw(mask)
    radius = int(size * 0.22)
    md.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)

    # 添加书本图案
    draw = ImageDraw.Draw(out)
    cx, cy = size // 2, size // 2
    book_w = int(size * 0.5)
    book_h = int(size * 0.62)
    book_x = cx - book_w // 2
    book_y = cy - book_h // 2
    book_r = int(size * 0.04)
    # 书封面
    draw.rounded_rectangle(
        (book_x, book_y, book_x + book_w, book_y + book_h),
        radius=book_r,
        fill=(255, 255, 255, 230),
    )
    # 书脊
    draw.line(
        [(cx, book_y + int(book_h * 0.06)), (cx, book_y + int(book_h * 0.94))],
        fill=(56, 132, 255, 255),
        width=max(2, size // 64),
    )
    # 书页横线
    line_color = (120, 130, 160, 255)
    lw = max(1, size // 80)
    for i in range(1, 5):
        ly = book_y + int(book_h * (0.22 + 0.14 * i))
        x0 = book_x + int(book_w * 0.12)
        x1 = book_x + int(book_w * 0.46)
        draw.line([(x0, ly), (x1, ly)], fill=line_color, width=lw)
        x0 = book_x + int(book_w * 0.54)
        x1 = book_x + int(book_w * 0.88)
        draw.line([(x0, ly), (x1, ly)], fill=line_color, width=lw)
    return out


def main() -> None:
    sizes = {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "icon.png": 512,
    }
    for name, size in sizes.items():
        path = os.path.join(OUTPUT_DIR, name)
        img = draw_icon(size)
        img.save(path, "PNG", optimize=True)
        print(f"已生成: {path} ({size}x{size})")

    # 简易 ICO（多尺寸）
    ico_sizes = [16, 32, 48, 64, 128, 256]
    ico_imgs = [draw_icon(s) for s in ico_sizes]
    ico_path = os.path.join(OUTPUT_DIR, "icon.ico")
    ico_imgs[0].save(
        ico_path,
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
        append_images=ico_imgs[1:],
    )
    print(f"已生成: {ico_path}")

    # 简易 ICNS（macOS 不会用，但 Tauri 要求存在）
    icns_path = os.path.join(OUTPUT_DIR, "icon.icns")
    draw_icon(512).save(icns_path, "ICNS")
    print(f"已生成: {icns_path}")


if __name__ == "__main__":
    main()
