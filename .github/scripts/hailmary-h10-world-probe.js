const {chromium}=require('playwright-core');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/usr/bin/google-chrome',args:['--no-sandbox','--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader','--enable-webgl']});const all={};
 for(const name of ['old','new']){
  const page=await browser.newPage({viewport:{width:1080,height:1920}});await page.addInitScript(()=>{window.filmHost=true;});
  await page.goto(`http://127.0.0.1:8765/${name}/room.html`,{waitUntil:'load',timeout:120000});await page.waitForFunction(()=>window.film&&window.film.ready,{timeout:120000});await page.evaluate(()=>window.film.ready);
  const frames=[];for(let t=0;t<=8;t+=.25){const v=await page.evaluate(t=>{window.film.frame(t);return window.__worldProbe()},t);frames.push({t,...v});}
  const angle=(a,b)=>{const dot=Math.abs(a.reduce((v,x,i)=>v+x*b[i],0));return 2*Math.acos(Math.min(1,dot))*180/Math.PI;};
  all[name]={max_head_world_degrees_from_start:Math.max(...frames.map(x=>angle(frames[0].head,x.head))),max_head_local_degrees_from_start:Math.max(...frames.map(x=>angle(frames[0].local,x.local))),max_camera_degrees_from_start:Math.max(...frames.map(x=>angle(frames[0].camera,x.camera))),max_world_change_per_quarter_second:Math.max(...frames.slice(1).map((x,i)=>angle(frames[i].head,x.head))),samples:frames.length};await page.close();
 }
 console.log('WORLD_PROBE',JSON.stringify(all));await browser.close();
})().catch(e=>{console.error(String(e));process.exit(1)});
