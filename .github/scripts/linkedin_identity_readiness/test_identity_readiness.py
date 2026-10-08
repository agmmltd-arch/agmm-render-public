import argparse,json,importlib.util,datetime
from pathlib import Path
from playwright.sync_api import sync_playwright,TimeoutError

def module(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def exercise(browser,m,label,delay=0,name='Samuel Wall',marker='AGMM',canonical=None):
 context=browser.new_context();page=context.new_page();canonical=canonical or m.PROFILE_URL
 html='<html><head><link rel="canonical" href="'+canonical+'"></head><body><h1>'+name+'</h1><p>CEO &amp; Co-Founder | @'+marker+' | Ai Consultancy</p>'
 if delay:html+='<script>const saved=document.body;document.body.remove();setTimeout(()=>document.documentElement.appendChild(saved),'+str(delay)+');</script>'
 html+='</body></html>'
 page.route('https://www.linkedin.com/**',lambda route: route.fulfill(status=200,content_type='text/html',body=html if '/in/me' in route.request.url else '<html><body>Feed</body></html>'))
 start=datetime.datetime.now(datetime.timezone.utc).isoformat()
 try:
  result=m.verify_identity(page);row={'label':label,'accepted':True,'identity_verified':result['verified'],'profile_url':result['profile_url']}
 except Exception as e:row={'label':label,'accepted':False,'error_class':type(e).__name__,'error':str(e)[:180]}
 finally:context.close()
 row.update(started_at=start,finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),delay_ms=delay);return row

p=argparse.ArgumentParser();p.add_argument('--before');p.add_argument('--candidate');p.add_argument('--output');a=p.parse_args();before=module(a.before,'old_identity');candidate=module(a.candidate,'new_identity');rows=[]
with sync_playwright() as pw:
 browser=pw.chromium.launch()
 rows.append(exercise(browser,before,'original_delayed_profile',delay=25000))
 rows.append(exercise(browser,candidate,'candidate_delayed_profile',delay=25000))
 rows.append(exercise(browser,candidate,'candidate_correct_profile'))
 rows.append(exercise(browser,candidate,'candidate_wrong_name',name='Another Person'))
 rows.append(exercise(browser,candidate,'candidate_wrong_marker',marker='DifferentCompany'))
 rows.append(exercise(browser,candidate,'candidate_wrong_url',canonical='https://www.linkedin.com/in/another-person/'))
 browser.close()
passed=not rows[0]['accepted'] and rows[0]['error_class']=='TimeoutError' and all(r['accepted'] for r in rows[1:3]) and all(not r['accepted'] and r['error_class']=='RuntimeError' for r in rows[3:])
result={'passed':passed,'results':rows,'account_or_public_action':False,'scope':'Exact runtime identity-body wait; delayed DOM fixture and strict identity refusals, not production timing/cause proof'};Path(a.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));raise SystemExit(0 if passed else 1)
