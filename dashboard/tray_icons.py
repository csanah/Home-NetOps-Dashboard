"""Shared tray icon drawing — used by tray.py, dashboard_tray.py, service_tray.py."""

from PIL import Image, ImageDraw


def make_icon_image(color):
    """Draw a filled circle icon with a server symbol, 256x256."""
    sz = 256
    img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([8, 8, sz - 8, sz - 8], fill=color)
    bar_w, bar_h = 140, 36
    x0 = (sz - bar_w) // 2
    gap = 8
    total_h = bar_h * 3 + gap * 2
    y_start = (sz - total_h) // 2
    for i in range(3):
        y = y_start + i * (bar_h + gap)
        draw.rounded_rectangle([x0, y, x0 + bar_w, y + bar_h], radius=8, fill="white")
        dot_r = 8
        dx = x0 + bar_w - 22
        dy = y + (bar_h - dot_r * 2) // 2
        draw.ellipse([dx, dy, dx + dot_r * 2, dy + dot_r * 2], fill=color)
    return img


ICONS = {
    "stopped": make_icon_image((220, 50, 50)),
    "starting": make_icon_image((220, 180, 30)),
    "running": make_icon_image((50, 200, 80)),
}
