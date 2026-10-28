#!/usr/bin/env python3
"""fe_formats.py (v2): the three format PRESETS of the format engine, as data. kit/tools/format_engine.py imports this.

v1 made three different card templates and was returned by root as a slideshow (S136, 20 Oct). v2 has ONE grammar, S05's (registry/storyboards/S05-storyboard.jpg): a dark WORLD
(real coastlines, a camera that travels), ONE hero tag that persists and comes back on the last frame, a known-name logo plate, condensed headlines that fill the width, real
source clippings with the clause marked, a bar chart the figure turns into, a legal pad, a CTA card. A FORMAT is now only a preset over that grammar:
  palette swatch (dark grounds, none navy or charcoal: concept_check R3), the face of the small kicker lines (serif / sans / condensed), the chip shapes (square, pill), and the
  concept axes it may claim (all are TRUE of what is drawn: the world is a map, the hero is the figure tag, the source is a clipping on the map).
Conflicts with FORMATS.md, resolved here and in review/p05.md: FORMATS.md section 1 asks for ONE carrier sheet re-laid beat by beat; root's gate (S136) rejected that as a slideshow
and asked for S05's world + hero + beats instead. CREATIVE-SCHOOL lesson 1 and DIRECTOR.md win over FORMATS.md.
"""

# ------------------------------------------------------------------------------------------------ swatches: dark, hue-coded, contrast measured against the ink
SWATCHES = {
    'D3': dict(fmt='dossier', name='oxblood', ground='#2b0f12', land='#3f1a1d', coast='#6a2d31', grid='#371518', pin='#e8b04a', ink='#f3e9d6', accent='#e8b04a', accent2='#9cc6e8', dim='#c4ae90', plate='#f4ecd8', plate_ink='#1b1712', pad='#f6e68a', tick='#a3221b', tag_fill='#f4ecd8', tag_ink='#1b1712', tag_rim='#c9bda2', tag_lab='#5b4f3a', tag_string='#d9cfb8', paper='#f4ecd8', gclass='dark-warm', hue='red', dark=True),
    'D5': dict(fmt='dossier', name='ink brown', ground='#1e1510', land='#31241b', coast='#5a4535', grid='#2a1e17', pin='#f0a830', ink='#f5ecdc', accent='#f0a830', accent2='#7fd0c0', dim='#c9b79b', plate='#f4ecd8', plate_ink='#1b1712', pad='#f6e68a', tick='#a3221b', tag_fill='#f4ecd8', tag_ink='#1b1712', tag_rim='#c9bda2', tag_lab='#5b4f3a', tag_string='#d9cfb8', paper='#f4ecd8', gclass='dark-warm', hue='amber', dark=True),
    'C4': dict(fmt='clean', name='night plum', ground='#24122e', land='#35204a', coast='#5f3d85', grid='#2e1a3d', pin='#ff8a3d', ink='#f6f0ff', accent='#ff8a3d', accent2='#5ce1c6', dim='#bcaad8', plate='#ffffff', plate_ink='#1a1030', pad='#f6e68a', tick='#1f8a5b', tag_fill='#ffffff', tag_ink='#1a1030', tag_rim='#d8cdee', tag_lab='#5a4a7a', tag_string='#cfc4e6', paper='#ffffff', gclass='dark-violet', hue='violet', dark=True),
    'C5': dict(fmt='clean', name='wine', ground='#2e0f28', land='#47193c', coast='#7a3365', grid='#3a1432', pin='#ffd23f', ink='#fbf1f6', accent='#ffd23f', accent2='#6ee7ff', dim='#d4b3c8', plate='#ffffff', plate_ink='#2a0f24', pad='#f6e68a', tick='#1f8a5b', tag_fill='#ffffff', tag_ink='#2a0f24', tag_rim='#e6cadb', tag_lab='#6a3a5c', tag_string='#e0c4d3', paper='#ffffff', gclass='dark-violet', hue='violet', dark=True),
    'N2': dict(fmt='newsroom', name='studio', ground='#0f2a20', land='#17402f', coast='#2c6b4f', grid='#14352a', pin='#ffcf33', ink='#f2f5f0', accent='#ffcf33', accent2='#ff7a7a', dim='#a9c9b8', plate='#e9efe6', plate_ink='#0c1a14', pad='#f6e68a', tick='#1f7a4f', tag_fill='#e9efe6', tag_ink='#0c1a14', tag_rim='#bfd0c4', tag_lab='#3f5a4c', tag_string='#cfe0d4', paper='#e9efe6', gclass='dark-green', hue='amber', dark=True),
    'N5': dict(fmt='newsroom', name='deep teal', ground='#0b2a2e', land='#12424a', coast='#23707c', grid='#0f343a', pin='#ff9f43', ink='#effafb', accent='#ff9f43', accent2='#8be9fd', dim='#a4cdd2', plate='#eaf6f6', plate_ink='#08191c', pad='#f6e68a', tick='#1f7a6a', tag_fill='#eaf6f6', tag_ink='#08191c', tag_rim='#bcd8da', tag_lab='#35585c', tag_string='#cde3e5', paper='#eaf6f6', gclass='dark-green', hue='teal', dark=True),
    "D6": dict(fmt="dossier", name="warm paper", ground="#f1e8d6", land="#d8c8a6", coast="#b7a27a", grid="#e2d5ba", pin="#b3261e", ink="#1b1712", accent="#b3261e", accent2="#1d4e89", dim="#6e6450", plate="#fffdf6", plate_ink="#1b1712", pad="#f6e68a", tick="#a3221b", tag_fill="#1b1712", tag_ink="#f7f1e3", tag_rim="#4a3f2e", tag_lab="#c9bda2", tag_string="#6e6450", paper="#fffdf6", gclass="light-warm", hue="red", dark=False),
    "C6": dict(fmt="clean", name="oat", ground="#efece3", land="#d2ccbb", coast="#a69c85", grid="#ddd7c8", pin="#c2410c", ink="#14171c", accent="#c2410c", accent2="#1d4ed8", dim="#667085", plate="#ffffff", plate_ink="#14171c", pad="#f6e68a", tick="#1f8a5b", tag_fill="#14171c", tag_ink="#f6f3ea", tag_rim="#3a4250", tag_lab="#b9c0cc", tag_string="#667085", paper="#ffffff", gclass="light-coolneutral", hue="orange", dark=False),
    "N6": dict(fmt="newsroom", name="newsprint warm", ground="#ece6d8", land="#d2c8ad", coast="#a69878", grid="#ddd4bd", pin="#0b4fb8", ink="#121212", accent="#0b4fb8", accent2="#b3141c", dim="#5f5b52", plate="#ffffff", plate_ink="#121212", pad="#f6e68a", tick="#1f7a4f", tag_fill="#121212", tag_ink="#f2efe6", tag_rim="#3a3a38", tag_lab="#c9c3b4", tag_string="#5f5b52", paper="#ffffff", gclass="light-warm", hue="blue", dark=False),
    "D7": dict(fmt="dossier", name="warm grey paper", ground="#b9b4ab", land="#cbc6bd", coast="#9a958b", grid="#aaa59c", pin="#b3261e", ink="#1b1712", accent="#b3261e", accent2="#1d4e89", dim="#5d584d", plate="#fffdf6", plate_ink="#1b1712", pad="#f6e68a", tick="#a3221b", tag_fill="#1b1712", tag_ink="#f7f1e3", tag_rim="#4a3f2e", tag_lab="#c9bda2", tag_string="#5d584d", paper="#fffdf6", gclass="light-warm", hue="red", dark=False),
    "C7": dict(fmt="clean", name="cool grey", ground="#b4b6ba", land="#c6c8cc", coast="#97999e", grid="#a5a7ab", pin="#c2410c", ink="#14171c", accent="#c2410c", accent2="#1d4ed8", dim="#575c66", plate="#ffffff", plate_ink="#14171c", pad="#f6e68a", tick="#1f8a5b", tag_fill="#14171c", tag_ink="#f6f3ea", tag_rim="#3a4250", tag_lab="#b9c0cc", tag_string="#575c66", paper="#ffffff", gclass="light-coolneutral", hue="orange", dark=False),
    "N7": dict(fmt="newsroom", name="newsprint grey", ground="#b8b5ae", land="#cac7c0", coast="#99958d", grid="#a9a6a0", pin="#0b4fb8", ink="#121212", accent="#0b4fb8", accent2="#b3141c", dim="#57544d", plate="#ffffff", plate_ink="#121212", pad="#f6e68a", tick="#1f7a4f", tag_fill="#121212", tag_ink="#f2efe6", tag_rim="#3a3a38", tag_lab="#c9c3b4", tag_string="#57544d", paper="#ffffff", gclass="light-warm", hue="blue", dark=False),
}

FORMATS = {
    "dossier": dict(
        slots=['centre-low', 'head-below', 'left-top', 'right-below', 'left-below', 'right-top'],
        name="DOSSIER", look="dossier", kface="serif", chip_r=10, z=0.86, w=14.0, swatches=["D3", "D5"], swatches_light=["D7", "D6"],
        world=["map-plan"], hero=["giant-number", "source-artifact"], signature=["stamp-verdict", "scan-sweep"], source=["pinned-clipping", "paper-document", "cream-card"],
        type_voice=dict(display="condensed-caps", kicker="serif", fonts=["Big Shoulders", "Source Serif"]), camera="pan", hook_mechanic="number-slam", filler="pen sweep",
        banned=["a wall or board of documents, red string, pins on cork", "CONFIDENTIAL, TOP SECRET or EXHIBIT A stamps no court said", "redaction bars or any altered crop",
                "typewriter or handwriting fonts and signatures that spell a name", "a figure counting up or in any colour but the accent"]),
    "clean": dict(
        slots=['centre-low', 'right-top', 'head-below', 'left-below', 'right-below', 'left-top'],
        name="CLEAN EXPLAINER", look="explainer", kface="sans", chip_r=44, z=0.80, w=18.0, swatches=["C4", "C5"], swatches_light=["C7", "C6"],
        world=["map-plan"], hero=["giant-number", "chart-diagram"], signature=["scan-sweep", "stamp-verdict"], source=["cream-card", "pinned-clipping", "on-object"],
        type_voice=dict(display="condensed-caps", kicker="sans", fonts=["Big Shoulders", "Space Grotesk"]), camera="pan", hook_mechanic="number-slam", filler="cell light",
        banned=["more than one figure object on screen", "chart axes or gridlines without values", "pie charts, donuts, 3D extrusion, isometric art",
                "icons, emoji, clip art or stock pictograms", "a ticking counter or a figure passing through numbers it never was"]),
    "newsroom": dict(
        slots=['centre-low', 'left-top', 'right-below', 'head-below', 'right-top', 'left-below'],
        name="NEWSROOM", look="newsroom", kface="cond", chip_r=6, z=0.84, w=20.0, swatches=["N2", "N5"], swatches_light=["N7", "N6"],
        world=["map-plan"], hero=["giant-number", "ui-surface"], signature=["scan-sweep", "stamp-verdict"], source=["strip-ticker", "screen-window", "pinned-clipping"],
        type_voice=dict(display="condensed-caps", kicker="sans", fonts=["Big Shoulders"]), camera="pan", hook_mechanic="number-slam", filler="flap click",
        banned=["fake channel names, BREAKING NEWS banners or LIVE badges", "a scrolling crawl", "glitch, VHS, scanlines, RGB split or signal-loss effects", "a presenter, a face or a silhouette",
                "rows of made-up figures to fill the board", "a reply card without the company's own words"]),
}

# object names for the R7 pitch (constructed, tied to a spoken word)
OBJECT_NAME = {"map": "world map the camera travels", "tag": "hanging figure tag", "plate": "known-name logo plate"}
