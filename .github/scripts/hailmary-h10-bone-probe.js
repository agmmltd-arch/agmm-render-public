const {chromium}=require('playwright-core');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/usr/bin/google-chrome',args:['--no-sandbox','--enable-unsafe-swiftshader','--use-gl=angle','--use-angle=swiftshader','--enable-webgl']});
 const all={};
 for (const name of ['old','new']){
  const page=await browser.newPage({viewport:{width:1080,height:1920}});await page.addInitScript(()=>{window.filmHost=true;});
  await page.goto(`http://127.0.0.1:8765/${name}/room.html`,{waitUntil:'load',timeout:120000});
  await page.waitForFunction(()=>window.film&&window.film.ready,{timeout:120000});await page.evaluate(()=>window.film.ready);
  const frames=[];
  for(let t=0;t<=8;t+=.5){
   const state=await page.evaluate(t=>{window.film.frame(t);return window.__headProbe()},t);
   if(!state.head||!state.neck)throw Error('Head or neck bone absent in '+name);
   frames.push({t,...state});
  }
  const angle=(a,b)=>{let dot=Math.abs(a.reduce((v,x,i)=>v+x*b[i],0));return 2*Math.acos(Math.min(1,dot))*180/Math.PI;};
  all[name]={max_head_degrees_from_first:Math.max(...frames.map(x=>angle(frames[0].head,x.head))),max_neck_degrees_from_first:Math.max(...frames.map(x=>angle(frames[0].neck,x.neck))),samples:frames.length};
  await page.close();
 }
 console.log(JSON.stringify(all));await browser.close();
})().catch(e=>{console.error(String(e));process.exit(1)});
