from pathlib import Path
import json, re
root=Path(__file__).parent
s=(root/'index.html').read_text()
manifest=json.loads((root/'SOURCE-MANIFEST.json').read_text())
assert 'data-composition-id="film05-first-act-wave10"' in s
assert 'data-duration="27.9"' in s
assert len(re.findall(r'class="[^"]*\bclip\b[^"]*"',s))==18
for phrase in ('FICTIONAL EXAMPLE','Compare supplier quotations','NO MODEL RUN','INPUTS ONLY','Replacement proposal','RECOMMENDATION STAYS WITH PRIYA','ILLUSTRATIVE FOOTAGE · FICTIONAL EXAMPLE','INCLUDED','EXCLUDED','PERSON TO CHECK','NO RECOMMENDATION OR CUSTOMER OUTCOME SHOWN','COMPARE THEM FOR WHAT?'):
    assert phrase in s, phrase
assert manifest['hosted_only_media_acquisition'] is True
assert json.loads((root/'package.json').read_text())['name']=='film05-first-act-wave10'
assert len(manifest['assets'])==2
for asset in manifest['assets']:
    assert asset['download_url'].startswith('https://videos.pexels.com/video-files/')
    assert asset['page'].startswith('https://www.pexels.com/video/')
    assert asset['hosted_sha256'] in ('fd6794301d75c022bd5ac32c94d5a2019ec8e450f06daa735e9428d460d118a4','2818f79b43d9c4121ece9003a65976b8cb817d88c85af40ba58c56bb88b3b887')
assert not list(root.rglob('*.mp4')) and not list(root.rglob('*.wav')) and not list(root.rglob('*.mp3'))
for name in ('request-and-proposal.png','folder-push.png','folder-push-after.png','blank-monitor.png','priya-before.png','priya-middle.png','priya-question.png','customer-equipment-room.png','field-bench-before.png','field-bench-after.png','supplier-files-before.png','supplier-files-after.png','gsap.min.js'):
    assert (root/'assets'/name).is_file(),name
print('TEXT SOURCE PASS: 27.9s, original 18.3s retained, operations boundary and proposal-tray actions present; media URLs and hosted receipts pinned; no programme video/audio files local')
