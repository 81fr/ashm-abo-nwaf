from PIL import Image, ImageDraw, ImageFont
import os

# Configuration
width, height = 500, 500
background_color = (10, 10, 10)  # Black
gold_color = (212, 175, 55)      # Gold
text_color = (255, 255, 255)     # White

# Create image
image = Image.new('RGB', (width, height), background_color)
draw = ImageDraw.Draw(image)

# Draw circle border
center = (width // 2, height // 2)
radius = 200
draw.ellipse((center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius), outline=gold_color, width=10)

# Draw "EAGLES" text (simple fallback if font not found)
try:
    # Try using a default font, size 40
    font = ImageFont.truetype("arial.ttf", 60)
except IOError:
    font = ImageFont.load_default()

text = "EAGLES"
text_bbox = draw.textbbox((0, 0), text, font=font)
text_width = text_bbox[2] - text_bbox[0]
text_height = text_bbox[3] - text_bbox[1]
draw.text(((width - text_width) / 2, height // 2 - 80), text, font=font, fill=gold_color)

text2 = "OF SPX"
text2_bbox = draw.textbbox((0, 0), text2, font=font)
text2_width = text2_bbox[2] - text2_bbox[0]
draw.text(((width - text2_width) / 2, height // 2 + 10), text2, font=font, fill=text_color)

# Draw stylized eagle (triangle)
# points = [(center[0], center[1] - 50), (center[0] - 40, center[1] + 30), (center[0] + 40, center[1] + 30)]
# draw.polygon(points, fill=gold_color)

# Ensure directory exists
output_dir = r"a:\سوق\web\static\images"
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

output_path = os.path.join(output_dir, "logo.png")
image.save(output_path)
print(f"Logo saved to {output_path}")
