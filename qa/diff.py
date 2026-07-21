import sys
from PIL import Image, ImageChops
def cmp(a, b):
    ia, ib = Image.open(a).convert('RGB'), Image.open(b).convert('RGB')
    if ia.size != ib.size:
        print(f'{a} vs {b}: SIZE MISMATCH {ia.size} vs {ib.size}')
        return
    diff = ImageChops.difference(ia, ib)
    hist = diff.convert('L').histogram()
    total = ia.size[0]*ia.size[1]
    changed = sum(hist[8:])          # pixels differing by >7/255
    strong = sum(hist[32:])          # pixels differing by >31/255
    print(f'{a.split("/")[-1]}: {ia.size} changed>7: {changed/total*100:.2f}%  changed>31: {strong/total*100:.3f}%')
for n in ['desktop-viewport','mobile-viewport','desktop-full','mobile-full']:
    cmp(f'qa/screens/ref-{n}.png', f'qa/screens/new-{n}.png')
