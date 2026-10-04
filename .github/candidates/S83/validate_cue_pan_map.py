#!/usr/bin/env python3
"""Validate exact S83 cue-to-visual binding and source-derived stereo pan."""
import json, math, re
from pathlib import Path

def _rule(html, selector):
    match=re.search(re.escape(selector)+r'\s*\{([^}]*)\}',html)
    if not match: raise ValueError('required source CSS rule absent: '+selector)
    return match.group(1)

def _px(rule, prop):
    match=re.search(r'(?:^|;)\s*'+re.escape(prop)+r'\s*:\s*(-?[0-9.]+)px\s*(?:;|$)',rule)
    if not match: raise ValueError('required source CSS pixel property absent: '+prop)
    return float(match.group(1))

def _metric_onset_x(html, width):
    metric=_rule(html,'.s1 .metric')
    left=_px(metric,'left'); right=_px(metric,'right')
    target=_rule(html,'.s1 .metric .value')
    if '<div class="value">' not in html or ('display:' in target and not re.search(r'(?:^|;)\s*display\s*:\s*block\s*(?:;|$)',target)):
        raise ValueError('metric value is no longer a full-width block; recompute its painted bounds')
    snippet=".fromTo('.s1 .value', { scale: .62, opacity: 0, transformOrigin: 'left center' }, { scale: 1, opacity: 1, duration: .68, ease: 'back.out(1.08)' }, .28)"
    if snippet not in html: raise ValueError('metric onset scale/origin changed; recompute position')
    # The value div fills its metric containing block. At the cue onset the .62
    # scale is left-origin, so its box centre is left + width * scale / 2.
    scale=.62
    return left+(width-left-right)*scale/2

def _evidence_state_x(html, width):
    turnover=_rule(html,'.turnover')
    left=_px(turnover,'left'); right=_px(turnover,'right')
    face_back=_rule(html,'.face-back')
    if not re.search(r'grid-template-columns\s*:\s*1fr\s+1fr\s*(?:;|$)',face_back):
        raise ValueError('back-face is no longer two equal columns; recompute evidence-state position')
    state=_rule(html,'.evidence-state')
    state_left=_px(state,'left'); state_right=_px(state,'right')
    ledger=_rule(html,'.ledger-column')
    if not re.search(r'(?:^|;)\s*position\s*:\s*relative\s*(?:;|$)',ledger):
        raise ValueError('evidence-state containing block changed; recompute position')
    if 'transform:rotateY(180deg)' not in face_back:
        raise ValueError('back-face orientation changed; recompute visible column position')
    flip=".fromTo('.turnover', { rotationY: 0 }, { rotationY: 180, duration: .78, ease: 'power2.inOut' }, 34.533)"
    if flip not in html:
        raise ValueError('turnover flip timeline changed; recompute visible column position')
    # The parent flip and back-face flip compose to face-on. The grid's
    # content box excludes the face border; target centre is the second column.
    box_width=width-left-right
    face=_rule(html,'.face')
    border=re.search(r'(?:^|;)\s*border\s*:\s*([0-9.]+)px\s+solid\b',face)
    if not border: raise ValueError('face border geometry changed; recompute evidence-state position')
    border_px=float(border.group(1))
    cell=(box_width-2*border_px)/2
    return left+border_px+cell+state_left+(cell-state_left-state_right)/2

def validate(spec_path, map_path, html_path):
    spec=json.loads(Path(spec_path).read_text()); doc=json.loads(Path(map_path).read_text()); html=Path(html_path).read_text()
    cues=spec['sfx']['cues']; rows=doc['cues']
    if len(cues)!=17 or len(rows)!=17 or doc['viewport_width_px']!=1080 or doc['pan_max']!=0.7:
        raise ValueError('exact cue map/runtime geometry required')
    if len({(x['sfx_id'],x['cue_time_seconds']) for x in rows})!=17:
        raise ValueError('duplicate cue mapping')
    for cue,row in zip(cues,rows):
        if (cue['sfx_id'],cue['t'],cue['event'],cue.get('pan')) != (row['sfx_id'],row['cue_time_seconds'],row['event'],row['pan']):
            raise ValueError('cue identity/time/event/pan mismatch: '+cue['sfx_id'])
        if row['selector'] not in html or row['timeline_snippet'] not in html:
            raise ValueError('cue selector/timeline binding absent from source: '+cue['sfx_id'])
        expected=round(max(-0.7,min(0.7,0.7*(2*row['cue_x_at_onset_px']/1080-1))),2)
        if not math.isfinite(row['cue_x_at_onset_px']) or row['pan']!=expected:
            raise ValueError('pan is not derived from the mapped event position: '+cue['sfx_id'])
        if not -0.7<=cue['pan']<=0.7:
            raise ValueError('pan exceeds pinned runtime bounds')
    metric=rows[1]
    if metric['selector']!='.s1 .value' or abs(metric['cue_x_at_onset_px']-_metric_onset_x(html,1080))>0.01:
        raise ValueError('metric cue position does not match CSS box and left-origin tween at onset')
    state=rows[13]
    if abs(state['cue_x_at_onset_px']-_evidence_state_x(html,1080))>0.01:
        raise ValueError('evidence-state cue position does not match its right-column CSS geometry')
    if rows[8]['cue_x_at_onset_px']!=208 or rows[16]['cue_x_at_onset_px']!=200:
        raise ValueError('drawing cue anchors must remain their left-edge start points')
    return len(cues)
if __name__=='__main__':
    import sys
    print('CUE_PAN_MAP_VALID cues='+str(validate(sys.argv[1],sys.argv[2],sys.argv[3])))
