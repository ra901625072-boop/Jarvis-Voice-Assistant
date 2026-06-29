import io
import base64
from PIL import Image

def optimize_image(img: Image.Image, max_dim=(1280, 720), quality=85) -> str:
    """
    Compresses and resizes PIL Image to optimize upload speed.
    Returns the base64 encoded string of the JPEG.
    """
    # Create a copy so we don't modify the original in place if it is reused
    optimized_img = img.copy()
    if optimized_img.width > max_dim[0] or optimized_img.height > max_dim[1]:
        optimized_img.thumbnail(max_dim, Image.Resampling.LANCZOS)
    
    buf = io.BytesIO()
    optimized_img.save(buf, format="JPEG", quality=quality)
    img_bytes = buf.getvalue()
    return base64.b64encode(img_bytes).decode('utf-8')
