from typing import Any


def convert_bbox(
    pixel_xyxy: list[float],
    image_width: int,
    image_height: int,
    page_width_pt: float,
    page_height_pt: float,
    rotation: int = 0,
) -> dict[str, Any]:
    if not pixel_xyxy or len(pixel_xyxy) != 4:
        return {"pixel_xyxy": [], "normalized_xyxy": [], "pdf_points_xyxy": []}

    x1, y1, x2, y2 = pixel_xyxy

    if rotation == 90:
        orig_x1, orig_y1 = y1, image_width - x2
        orig_x2, orig_y2 = y2, image_width - x1
        x1, y1, x2, y2 = orig_x1, orig_y1, orig_x2, orig_y2
    elif rotation == 180:
        x1, y1, x2, y2 = image_width - x2, image_height - y2, image_width - x1, image_height - y1
    elif rotation == 270:
        orig_x1, orig_y1 = image_height - y2, x1
        orig_x2, orig_y2 = image_height - y1, x2
        x1, y1, x2, y2 = orig_x1, orig_y1, orig_x2, orig_y2

    norm_x1 = round(x1 / max(image_width, 1), 4)
    norm_y1 = round(y1 / max(image_height, 1), 4)
    norm_x2 = round(x2 / max(image_width, 1), 4)
    norm_y2 = round(y2 / max(image_height, 1), 4)

    pt_x1 = round(norm_x1 * page_width_pt, 2)
    pt_y1 = round(norm_y1 * page_height_pt, 2)
    pt_x2 = round(norm_x2 * page_width_pt, 2)
    pt_y2 = round(norm_y2 * page_height_pt, 2)

    return {
        "pixel_xyxy": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
        "normalized_xyxy": [norm_x1, norm_y1, norm_x2, norm_y2],
        "pdf_points_xyxy": [pt_x1, pt_y1, pt_x2, pt_y2],
    }
