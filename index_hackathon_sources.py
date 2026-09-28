from pathlib import Path
import json
import hashlib
import csv
import pymupdf
from PIL import Image, ImageOps, ImageDraw

SOURCE = Path(r'C:\Users\USER\Downloads\GUJ')
OUT = Path(r'C:\Users\USER\Documents\ChatGPT\Project GUJ\hackathon_source_index')
OUT.mkdir(parents=True, exist_ok=True)

txt_path = SOURCE / 'GUJtxt.txt'
pdf_path = SOURCE / 'GUJ.pdf'
raw_txt = txt_path.read_text(encoding='utf-8-sig')
txt_lines = raw_txt.splitlines()
with (OUT / 'GUJtxt_lines.tsv').open('w', encoding='utf-8', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(['line', 'text'])
    w.writerows((i, line) for i, line in enumerate(txt_lines, 1))

doc = pymupdf.open(pdf_path)
pages = []
images = []
with (OUT / 'GUJpdf_pages_and_lines.tsv').open('w', encoding='utf-8', newline='') as f:
    w = csv.writer(f, delimiter='\t')
    w.writerow(['page', 'extracted_line', 'text'])
    for pno, page in enumerate(doc, 1):
        text = page.get_text(sort=True)
        lines = text.splitlines()
        w.writerows((pno, i, line) for i, line in enumerate(lines, 1))
        pages.append({'page': pno, 'text': text, 'image_count': len(page.get_images(full=True))})
        for ino, image_ref in enumerate(page.get_images(full=True), 1):
            xref = image_ref[0]
            extracted = doc.extract_image(xref)
            ext = extracted['ext']
            name = f'pdf_image_p{pno:02d}_{ino:02d}.{ext}'
            (OUT / name).write_bytes(extracted['image'])
            images.append({'page': pno, 'image': ino, 'xref': xref, 'file': name, 'width': extracted['width'], 'height': extracted['height'], 'page_rects': [list(r) for r in page.get_image_rects(xref)]})

thumbs = []
for pno, page in enumerate(doc, 1):
    pix = page.get_pixmap(matrix=pymupdf.Matrix(1, 1), alpha=False)
    im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    im.thumbnail((420, 540))
    tile = Image.new('RGB', (440, 580), 'white')
    tile.paste(im, ((440-im.width)//2, 30))
    ImageDraw.Draw(tile).text((10, 8), f'Page {pno}', fill='black')
    thumbs.append(tile)
    if pno in (1, 2, 5, 7):
        pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        pix.save(OUT / f'page_{pno:02d}.png')

for start in (0, 10):
    sheet = Image.new('RGB', (440*5, 580*2), '#dddddd')
    for j, tile in enumerate(thumbs[start:start+10]):
        sheet.paste(tile, ((j%5)*440, (j//5)*580))
    sheet.save(OUT / f'contact_sheet_{start//10+1}.png')

manifest = {
    'sources': [
        {'file': str(txt_path), 'sha256': hashlib.sha256(txt_path.read_bytes()).hexdigest(), 'line_count': len(txt_lines), 'bytes': txt_path.stat().st_size},
        {'file': str(pdf_path), 'sha256': hashlib.sha256(pdf_path.read_bytes()).hexdigest(), 'page_count': len(doc), 'bytes': pdf_path.stat().st_size},
    ],
    'pdf_pages': pages,
    'pdf_images': images,
}
(OUT / 'full_text.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'txt_lines': len(txt_lines), 'pdf_pages': len(doc), 'pdf_images': sum(x['image_count'] for x in pages), 'out': str(OUT)}, indent=2))
