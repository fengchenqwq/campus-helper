# 图片识别接口测试：生成带文字图片，上传到 /api/image
from PIL import Image, ImageDraw, ImageFont

import httpx

# 1. 生成测试图片（带英文文字，避免中文字体问题）
img = Image.new('RGB', (600, 200), 'white')
draw = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 40)
except Exception:
    font = ImageFont.load_default()
draw.text((30, 70), 'Library Open 8:00-22:00', fill='black', font=font)
path = 'C:/Users/14218/Desktop/school/test/test_image.png'
img.save(path)
print('test image saved:', path)

# 2. 上传测试
with open(path, 'rb') as f:
    files = {'file': ('test_image.png', f, 'image/png')}
    resp = httpx.post('http://127.0.0.1:8000/api/image', files=files, timeout=120)

result = resp.json()
print('code:', result.get('code'))
text = (result.get('data') or {}).get('text', '')
print('recognized text length:', len(text))
open('C:/Users/14218/Desktop/school/test/image_result.txt', 'w', encoding='utf-8').write(text)
print('result saved to test/image_result.txt')
