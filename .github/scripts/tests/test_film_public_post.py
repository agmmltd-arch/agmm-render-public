import unittest
from film_public_post import validate_public_result, validate_approval_freshness, validate_av_review, validate_plan_identity, CHANNEL_ID
from youtube_studio_cloud_upload import observed_studio_channel_id, guarded_studio_action
class T(unittest.TestCase):
 def req(self):return {'master_sha256':'a'*64,'source_run_id':'123456','title':'T','thumbnail_sha256':'b'*64,'channel_id':CHANNEL_ID,'source_commit':'c'*40,'film_id':'F02','post_id':'p','target_date':'2026-10-05','package':{'video':{'sha256':'a'*64}},'description':'D','approval':{'review_sha256':'d'*64},'rights':{}}
 def res(self):return {'schema':'agmm-youtube-cloud-studio-public-v1','overall':'PUBLIC_VERIFIED','studio_state':'PUBLIC','master_sha256':'a'*64,'source_run_id':'123456','title':'T','thumbnail_sha256':'b'*64,'oembed':{'author_name':'AGMM','title':'T'},'studio_thumbnail_mean_abs_distance':1,'video_id':'abcdefghijk','post_url':'https://www.youtube.com/watch?v=abcdefghijk','channel_id':CHANNEL_ID}
 def bad(self,f):
  x=self.res();f(x)
  with self.assertRaises(ValueError):validate_public_result(self.req(),x)
 def test_review_predates_master(self):
  with self.assertRaises(ValueError): validate_approval_freshness({"approved_at":"2026-10-05T00:30:00+01:00"},{"reviewed_at":"2026-10-05T00:00:00+01:00"},"2026-10-04T23:30:00+01:00")
 def test_approval_before_review(self):
  with self.assertRaises(ValueError): validate_approval_freshness({"approved_at":"2026-10-04T23:30:00+01:00"},{"reviewed_at":"2026-10-05T00:00:00+01:00"},"2026-10-04T22:00:00+01:00")
 def test_future_approval(self):
  with self.assertRaises(ValueError): validate_approval_freshness({"approved_at":"2099-10-05T10:00:00+01:00"},{"reviewed_at":"2026-10-05T00:00:00+01:00"},"2026-10-04T22:00:00+01:00")
 def test_wrong_profile_preupload_refuses(self):
  with self.assertRaises(RuntimeError): observed_studio_channel_id('https://studio.youtube.com/channel/OTHER/videos/upload', [])
 def test_wrong_profile_has_no_upload_or_publish_side_effect(self):
  class Links:
   def evaluate_all(self,script):return []
  class Page:
   url='https://studio.youtube.com/channel/WRONG/video/upload'
   def locator(self,selector):return Links()
  effects=[]
  with self.assertRaises(RuntimeError):guarded_studio_action(Page(),CHANNEL_ID,lambda:effects.append('side-effect'))
  self.assertEqual(effects,[])
 def test_expected_profile_preupload(self):self.assertEqual(observed_studio_channel_id('https://studio.youtube.com/channel/'+CHANNEL_ID+'/videos/upload', []),CHANNEL_ID)
 def test_missing_av_gate(self):
  review={'overall':'PASS','film_id':'F02','master_sha256':'a'*64,'reviewer_id':'r','maker_id':'m','audiovisual_review':{'continuous_visual':'PASS'}}
  with self.assertRaises(ValueError):validate_av_review(review,'F02','a'*64)
 def test_plan_date_mismatch(self):
  with self.assertRaises(ValueError):validate_plan_identity({'channel_id':CHANNEL_ID,'posted':[]},{'film_id':'F02','status':'Ready to post','target_date':'2026-10-04','channel_id':CHANNEL_ID,'master_sha256':'a'*64},'F02','2026-10-05')
 def test_duplicate_refused(self):
  with self.assertRaises(ValueError):validate_plan_identity({'channel_id':CHANNEL_ID,'posted':[{'film_id':'F02'}]},{'film_id':'F02','status':'Ready to post','target_date':'2026-10-05','channel_id':CHANNEL_ID,'master_sha256':'a'*64},'F02','2026-10-05')
 def test_accept(self):self.assertEqual(validate_public_result(self.req(),self.res())['video_id'],'abcdefghijk')
 def test_private(self):self.bad(lambda x:x.update(studio_state='PRIVATE'))
 def test_not_public(self):self.bad(lambda x:x.update(overall='PRIVATE_ONLY'))
 def test_wrong_hash(self):self.bad(lambda x:x.update(master_sha256='0'*64))
 def test_stale_approval(self):self.bad(lambda x:x.update(title='old'))
 def test_wrong_profile(self):self.bad(lambda x:x.update(channel_id='wrong'))
 def test_wrong_run(self):self.bad(lambda x:x.update(source_run_id='654321'))
 def test_bad_url(self):self.bad(lambda x:x.update(post_url=''))
if __name__=='__main__':unittest.main()
