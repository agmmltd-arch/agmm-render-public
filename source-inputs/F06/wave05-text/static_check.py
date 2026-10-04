from pathlib import Path
import re

root = Path(__file__).resolve().parent
html = (root / 'index.html').read_text()
assert 'data-duration="9.6"' in html
assert html.count('class="clip"') == 9
assert 'ILLUSTRATIVE SCENARIO' in html
assert 'ONE DELIVERY ONLY' in html
assert 'REVIEW REQUIRED' in html and 'HOLD CUSTOMER REPLY' in html
assert 'id="release"' in html and 'board-release-action.png' in html
assert 'STAFF ROTA PENDING' in html and 'PENDING REVIEW' in html
assert 'CHECK CARTONS TOGETHER' in html and 'APPROVED BEFORE CHANGE' in html
assert "window.__timelines['film06-opening-wave05']" in html
assert not list(root.rglob('*.wav')) and not list(root.rglob('*.mp3')) and not list(root.rglob('*.mp4'))
for name in ('amendment.webp', 'board-cleared.webp', 'board-hand-action.webp', 'sales-desk.webp', 'venue-bay.webp', 'packing-table.webp'):
    path = root / 'assets' / name
    assert path.is_file() and path.stat().st_size < 1_000_000
    assert path.read_bytes()[:4] == b'RIFF'
    assert html.count(name) == 1
review = root / 'assets' / 'board-review.webp'
assert review.is_file() and review.stat().st_size < 1_000_000
assert review.read_bytes()[:4] == b'RIFF' and html.count('board-review.webp') == 2
release = root / 'assets' / 'board-release-action.png'
assert release.is_file() and release.stat().st_size < 12_000_000
assert release.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
assert html.count('board-release-action.png') == 1
assert re.findall(r'data-start="([\d.]+)" data-duration="([\d.]+)"', html) == [
    ('0', '9.6'), ('0', '0.9'), ('0.9', '0.433333'), ('1.333333', '0.366667'),
    ('1.7', '0.2'), ('1.9', '0.4'), ('2.3', '1.566667'),
    ('3.866667', '0.533333'), ('4.4', '2.4'), ('6.8', '2.8'),
]
print('PASS 9.6s nine-scene silent source: visible key release, customer hold, venue rota and packing review')
