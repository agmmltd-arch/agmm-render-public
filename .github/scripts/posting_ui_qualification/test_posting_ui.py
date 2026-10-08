import ast,argparse,json,re,os,tempfile,html
from pathlib import Path
from playwright.sync_api import sync_playwright,TimeoutError as PlaywrightTimeoutError


def callable_region(path,kind):
 tree=ast.parse(Path(path).read_text());publish=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='publish')
 if kind=='linkedin':
  tries=[n for n in ast.walk(publish) if isinstance(n,ast.Try) and any(isinstance(x,ast.Constant) and x.value=='Start a post' for x in ast.walk(n)) and n is not next(x for x in ast.walk(publish) if isinstance(x,ast.Try))]
  if tries:chosen=min(tries,key=lambda n:n.end_lineno-n.lineno)
  else:chosen=next(n for n in ast.walk(publish) if isinstance(n,ast.Expr) and any(isinstance(x,ast.Constant) and x.value=='Start a post' for x in ast.walk(n)))
  body=[chosen,ast.Return(ast.Constant(True))]
 else:
  owner=next(n for n in ast.walk(publish) if isinstance(n,ast.Try) and any(isinstance(x,ast.Assign) and any(isinstance(y,ast.Name) and y.id=='uploaded' for y in x.targets) for x in n.body))
  begin=next(i for i,n in enumerate(owner.body) if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='uploaded' for x in n.targets))
  end=next(i for i,n in enumerate(owner.body[begin:],begin) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and n.value.func.attr=='sleep')
  body=owner.body[begin:end]+[ast.Return(ast.Name('uploaded',ast.Load()))]
 fn=ast.FunctionDef(name='actual_runtime_region',args=ast.arguments(posonlyargs=[],args=[ast.arg('page'),ast.arg('video'),ast.arg('package')],kwonlyargs=[],kw_defaults=[],defaults=[]),body=body,decorator_list=[])
 mod=ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]));ns={'re':re,'PlaywrightTimeoutError':PlaywrightTimeoutError,'PROFILE_NAME':'Samuel Wall','log':lambda x:None,'vr':type('Screenshot',(),{'screenshot':staticmethod(lambda *a:None)})};exec(compile(mod,str(path),'exec'),ns);return ns['actual_runtime_region']

class Locator:
 def __init__(self,real,click_fault=False):self.real=real;self.click_fault=click_fault
 @property
 def first(self):return Locator(self.real.first,self.click_fault)
 def click(self,**kw):
  self.real.click(timeout=500)
  if self.click_fault:raise PlaywrightTimeoutError('fixture: native-style click timeout after composer transition')
 def set_input_files(self,*a,**kw):kw['timeout']=250;return self.real.set_input_files(*a,**kw)
 def wait_for(self,**kw):kw['timeout']=250;return self.real.wait_for(**kw)
 def filter(self,**kw):return Locator(self.real.filter(**kw),self.click_fault)
 def locator(self,*a,**kw):return Locator(self.real.locator(*a,**kw))
 def __getattr__(self,k):return getattr(self.real,k)
class Page:
 def __init__(self,page,fault=False):self.page=page;self.fault=fault
 def get_by_role(self,role,**kw):return Locator(self.page.get_by_role(role,**kw),self.fault and role=='button' and isinstance(kw.get('name'),re.Pattern))
 def locator(self,*a,**kw):return Locator(self.page.locator(*a,**kw))
 def expect_file_chooser(self,**kw):return self.page.expect_file_chooser(timeout=1000)

def li_html(name='Samuel Wall',media=True,disabled=False,count=1,opens=True):
 dialog='<div role="dialog"><h2>'+name+'</h2>'+('<button aria-label="Media" '+('disabled' if disabled else '')+'>Media</button>' if media else '')+'</div>'
 return '<button onclick="document.querySelector(\'section\').innerHTML='+("JSON.parse(this.dataset.html)" if opens else "''")+'" data-html='+'"'+html.escape(json.dumps(dialog*count),quote=True)+'"'+'>Start a post</button><section></section>'
def yt_html(kind):
 if kind=='legacy':return '<input type="file" accept="video/*">'
 if kind=='missing':return '<p>Upload videos</p>'
 button='<button '+('disabled' if kind=='disabled' else '')+' onclick="const f=document.createElement(\'input\');f.type=\'file\';f.accept=\'video/*\';f.style.display=\'none\';document.body.append(f);f.click();">Select files</button>'
 return button*(2 if kind=='ambiguous' else 1)

def main():
 assert os.environ.get('GITHUB_ACTIONS')=='true','Browser checks belong on public Ubuntu'
 p=argparse.ArgumentParser();p.add_argument('--directory');p.add_argument('--output');a=p.parse_args();d=Path(a.directory);rows=[]
 li_old=callable_region(d/'before_linkedin.py','linkedin');li_new=callable_region(d/'candidate_linkedin.py','linkedin');yt_old=callable_region(d/'before_youtube.py','youtube');yt_new=callable_region(d/'candidate_youtube.py','youtube')
 fixture=Path(tempfile.gettempdir())/'agmm-picker-fixture.txt';fixture.write_text('local selector fixture; no programme media')
 with sync_playwright() as pw:
  browser=pw.chromium.launch(channel='chrome');page=browser.new_page();version=browser.version
  def attempt(label,fn,html,fault=False,expected=True):
   page.set_content(html)
   try:result=fn(Page(page,fault),fixture,Path('.'));accepted=result is True;error=None
   except Exception as e:accepted=False;error=type(e).__name__
   rows.append({'label':label,'accepted':accepted,'expected':expected,'passed':accepted==expected,'error':error})
   assert accepted==expected,label
  attempt('original_click_timed_out_after_open',li_old,li_html(),True,False)
  attempt('candidate_open_composer_confirmed',li_new,li_html(),True,True)
  attempt('candidate_normal_click',li_new,li_html(),False,True)
  for label,html in [('absent_composer',li_html(opens=False)),('wrong_name',li_html(name='Another Person')),('missing_media',li_html(media=False)),('disabled_media',li_html(disabled=True)),('ambiguous_composer',li_html(count=2))]:attempt('candidate_'+label,li_new,html,True,False)
  attempt('original_lazy_input',yt_old,yt_html('lazy'),False,False)
  attempt('candidate_lazy_input',yt_new,yt_html('lazy'),False,True)
  assert page.locator('input[type=file]').evaluate('(e)=>e.files[0].name')==fixture.name
  attempt('candidate_legacy_input',yt_new,yt_html('legacy'),False,True)
  for kind in ['missing','disabled','ambiguous']:attempt('candidate_picker_'+kind,yt_new,yt_html(kind),False,False)
  browser.close()
 result={'passed':all(x['passed'] for x in rows),'results':rows,'browser_version':version,'scope':'Exact runtime AST upload/click branches; current native control topology and injected post-click timeout paired with actual production screenshot. Fixture locator waits shortened; no account, programme media or public action.'};Path(a.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
