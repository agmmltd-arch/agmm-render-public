"""Hosted F02 OCR candidate frames. This is a sample, never release approval."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

RUN = 37125818648
REPO = 'agmmltd-arch/agmm-render-public'
PROXY = 'F02-MASTER-1080-from-4K.mp4'
TIMES = (36.5,39.5,41.5,42,88.5,89,89.5,208.5,209,209.5,210,358,
         430,430.5,431,436.5,437,437.5,439,439.5,440,555.5,556,
         604,605,607,607.5,610,612.5,615.5,616,616.5)


def guard():
    if platform.system() != 'Linux' or os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('Hosted Linux Actions runner required before media IO')

def proxy_contract(proof):
    if (proof.get('source_run_id') != RUN or proof.get('repository') != REPO
        or proof.get('review_status') != 'NOT_RUN'
        or proof.get('release_approval') != 'NOT_GRANTED'
        or proof.get('preview_status') != 'REPAIRS_REQUIRED'
        or proof.get('source_conclusion') != 'failure'):
        raise ValueError('Wrong source or review authority')
    files = proof.get('files', [])
    matches = [f for f in files if f.get('name') == PROXY]
    if len(matches) != 1:
        raise ValueError('Exact single viewing proxy required')
    f = matches[0]
    if (type(f.get('size')) is not int or not 0 < f['size'] < 2_000_000_000
        or not isinstance(f.get('sha256'), str) or len(f['sha256']) != 64
        or any(c not in '0123456789abcdef' for c in f['sha256'])
        or f.get('url') != f'https://github.com/{REPO}/releases/download/preview-F02-{RUN}/{PROXY}'):
        raise ValueError('Invalid proxy identity')
    return f

def main():
    guard()
    proof = json.loads(Path('preview-proof.json').read_text())
    contract = proxy_contract(proof)
    paths = list(Path('proxy').rglob(PROXY))
    if len(paths) != 1:
        raise ValueError('Exact single proxy artifact required')
    video = paths[0]
    digest = hashlib.sha256()
    with video.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    if video.stat().st_size != contract['size'] or digest.hexdigest() != contract['sha256']:
        raise ValueError('Proxy artifact does not match verified export')
    probe = json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
        '-show_entries','stream=width,height,r_frame_rate,nb_frames','-of','json',str(video)]))
    stream = probe['streams'][0]
    if (stream['width'], stream['height'], stream['r_frame_rate'], int(stream['nb_frames'])) != (1920,1080,'30/1',19548):
        raise ValueError('Unexpected exact source frame geometry/count')
    frames = [round(t*30) for t in TIMES]
    out = Path('review-evidence');out.mkdir(exist_ok=True)
    expression = '+'.join(f'eq(n,{n})' for n in frames)
    subprocess.run(['ffmpeg','-v','error','-threads','2','-i',str(video),'-vf',f"select='{expression}'",
        '-fps_mode','vfr','-frames:v',str(len(frames)),str(out/'frame-%03d.png')],check=True)
    pictures = sorted(out.glob('frame-*.png'))
    if len(pictures) != len(frames):
        raise ValueError('Candidate extraction incomplete')
    from PIL import Image, ImageDraw, ImageFont
    pages = []
    font = ImageFont.load_default(size=26)
    for number, time, path in zip(frames,TIMES,pictures):
        with Image.open(path) as image:
            if image.size != (1920,1080):
                raise ValueError('Unexpected extracted dimensions')
            page = Image.new('RGB',(1920,1240),'white');page.paste(image.convert('RGB'),(0,130))
        draw = ImageDraw.Draw(page)
        draw.text((24,12),f'F02 frame {number} at {number/30:.6f}s - OCR candidate, NOT a confirmed defect',font=font,fill='black')
        draw.text((24,49),f'{len(TIMES)} selected frames only. No full-film visual/audio review or release approval.',font=font,fill='black')
        draw.text((24,86),f'Proxy SHA256: {contract["sha256"]}',font=font,fill='black')
        page.save(out/f'candidate-{number:05d}.jpg',quality=95,subsampling=0)
        pages.append(page)
    pages[0].save(out/'F02-OCR-review-candidates.pdf',save_all=True,append_images=pages[1:],
                  resolution=144,quality=95,subsampling=0)
    receipt = {'source_run_id':RUN,'source_proxy_sha256':contract['sha256'],
        'source_proxy_size':contract['size'],'source_frame_count':19548,'fps':30,
        'reviewed':False,'release_approval':'NOT_GRANTED','scope':'OCR_CANDIDATE_SAMPLE',
        'frame_indices':frames,'frame_times':[n/30 for n in frames],'pages':len(pages)}
    (out/'candidate-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt))

if __name__ == '__main__':
    main()
