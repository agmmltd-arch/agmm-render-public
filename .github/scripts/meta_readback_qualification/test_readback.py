import ast,contextlib,sys,types,unittest
from pathlib import Path
from unittest.mock import Mock
SOURCE=Path(sys.argv.pop(1))
TEXT=SOURCE.read_text();TREE=ast.parse(TEXT)
class NavigationTimeout(Exception):pass
URL="https://www.facebook.com/reel/1234567890123456/"
CAPTION="Exact approved caption fixture"
def adapter():
    page=object();ctx=Mock();ctx.new_page.return_value=page
    pw=Mock();pw.chromium.launch_persistent_context.return_value=ctx
    namespace={"Path":Path,"mp":types.SimpleNamespace(find_meta_post_urls=Mock(return_value={"facebook":URL})),
      "profile_lock":lambda _:contextlib.nullcontext(),"META_PROFILE":"fixture-only",
      "sync_playwright":lambda:contextlib.nullcontext(pw),"caption_for":lambda *_:CAPTION,
      "_fb_public_from_published_row":Mock(return_value=URL),"log":Mock(),
      "PlaywrightTimeoutError":NavigationTimeout}
    nodes=[x for x in TREE.body if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name in ["reconcile_only","_read_committed_public_url"]]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SOURCE),"exec"),namespace)
    return namespace,page,ctx
class Readback(unittest.TestCase):
    def test_insights_timeout_reaches_facebook_fallback(self):
        n,p,c=adapter();n["mp"].find_meta_post_urls.side_effect=NavigationTimeout("actual observed insights navigation timeout")
        self.assertEqual(n["reconcile_only"](Path("/safe-fixture"),"facebook"),URL)
        n["_fb_public_from_published_row"].assert_called_once_with(p,CAPTION);c.close.assert_called_once()
    def test_normal_public_link_avoids_fallback(self):
        n,p,c=adapter();self.assertEqual(n["reconcile_only"](Path("/safe-fixture"),"facebook"),URL)
        n["_fb_public_from_published_row"].assert_not_called();c.close.assert_called_once()
    def test_empty_link_still_uses_strict_existing_fallback(self):
        n,p,c=adapter();n["mp"].find_meta_post_urls.return_value={}
        n["_fb_public_from_published_row"].return_value=""
        self.assertEqual(n["reconcile_only"](Path("/safe-fixture"),"facebook"),"")
        n["_fb_public_from_published_row"].assert_called_once_with(p,CAPTION)
    def test_instagram_timeout_stays_unresolved(self):
        n,p,c=adapter();n["mp"].find_meta_post_urls.side_effect=NavigationTimeout("timeout")
        with self.assertRaises(NavigationTimeout):n["reconcile_only"](Path("/safe-fixture"),"instagram")
        n["_fb_public_from_published_row"].assert_not_called();c.close.assert_called_once()
    def test_other_error_is_not_turned_into_a_url(self):
        n,p,c=adapter();n["mp"].find_meta_post_urls.side_effect=RuntimeError("unexpected failure")
        with self.assertRaises(RuntimeError):n["reconcile_only"](Path("/safe-fixture"),"facebook")
        n["_fb_public_from_published_row"].assert_not_called();c.close.assert_called_once()
    def test_prepublish_lookup_remains_direct_and_fail_closed(self):
        publish=next(x for x in TREE.body if isinstance(x,ast.FunctionDef) and x.name=="publish")
        calls=[x for x in ast.walk(publish) if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr=="find_meta_post_urls"]
        first=min(calls,key=lambda x:x.lineno)
        claims=[x for x in ast.walk(publish) if isinstance(x,ast.Call) and isinstance(x.func,ast.Attribute) and x.func.attr=="commit"]
        self.assertLess(first.lineno,min(x.lineno for x in claims))
        self.assertIn("if existing:",ast.get_source_segment(TEXT,publish))
if __name__=="__main__":unittest.main(verbosity=2)
