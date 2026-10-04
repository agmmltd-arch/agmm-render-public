import copy, json, tempfile, unittest
from pathlib import Path
from validate_cue_pan_map import validate

ROOT=Path(__file__).parent
CANDIDATE=ROOT
SPEC=ROOT/'MIX-SPEC.json'
MAP=ROOT/'MIX-CUE-PAN-MAP.json'
HTML=CANDIDATE/'index.html'

class CuePanMapTests(unittest.TestCase):
    def _run(self, spec=None, mapping=None, html=None):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            for name,obj,source in [('spec',spec,SPEC),('map',mapping,MAP)]:
                target=d/(name+'.json')
                target.write_text(json.dumps(obj if obj is not None else json.loads(source.read_text())))
            source_html=html if html is not None else HTML.read_text()
            (d/'index.html').write_text(source_html)
            return validate(d/'spec.json',d/'map.json',d/'index.html')
    def test_accepts_exact_17_source_bound_cues(self):
        self.assertEqual(self._run(),17)
    def test_rejects_changed_signed_pan(self):
        spec=json.loads(SPEC.read_text()); spec['sfx']['cues'][0]['pan']=0.7
        with self.assertRaisesRegex(ValueError,'identity/time/event/pan mismatch'):
            self._run(spec=spec)
    def test_rejects_cue_event_mismatch(self):
        spec=json.loads(SPEC.read_text()); spec['sfx']['cues'][3]['event']='unrelated card'
        with self.assertRaisesRegex(ValueError,'identity/time/event/pan mismatch'):
            self._run(spec=spec)
    def test_rejects_missing_source_timeline_binding(self):
        mapping=json.loads(MAP.read_text()); mapping['cues'][8]['timeline_snippet']='no such timeline event'
        with self.assertRaisesRegex(ValueError,'selector/timeline binding absent'):
            self._run(mapping=mapping)
    def test_rejects_center_not_matching_pan(self):
        mapping=json.loads(MAP.read_text()); mapping['cues'][14]['cue_x_at_onset_px']=900
        with self.assertRaisesRegex(ValueError,'not derived from the mapped event position'):
            self._run(mapping=mapping)
    def test_rejects_coordinated_wrong_metric_coordinate_and_pan(self):
        spec=json.loads(SPEC.read_text()); mapping=json.loads(MAP.read_text())
        spec['sfx']['cues'][1]['pan']=0.47
        mapping['cues'][1]['cue_x_at_onset_px']=900
        mapping['cues'][1]['pan']=0.47
        with self.assertRaisesRegex(ValueError,'metric cue position does not match CSS box'):
            self._run(spec=spec,mapping=mapping)
    def test_rejects_coordinated_wrong_evidence_column_coordinate_and_pan(self):
        spec=json.loads(SPEC.read_text()); mapping=json.loads(MAP.read_text())
        spec['sfx']['cues'][13]['pan']=0.0
        mapping['cues'][13]['cue_x_at_onset_px']=540
        mapping['cues'][13]['pan']=0.0
        with self.assertRaisesRegex(ValueError,'evidence-state cue position does not match'):
            self._run(spec=spec,mapping=mapping)
    def test_rejects_changed_metric_source_scale(self):
        html=HTML.read_text().replace("scale: .62, opacity: 0, transformOrigin: 'left center'","scale: .7, opacity: 0, transformOrigin: 'left center'")
        mapping=json.loads(MAP.read_text())
        mapping['cues'][1]['timeline_snippet']=mapping['cues'][1]['timeline_snippet'].replace('scale: .62','scale: .7')
        with self.assertRaisesRegex(ValueError,'metric onset scale/origin changed'):
            self._run(mapping=mapping,html=html)

if __name__=='__main__': unittest.main()
