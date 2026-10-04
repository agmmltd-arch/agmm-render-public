/* S90 isolated storyboard-development candidate. Not installed in kit/specs/S90.
   Concept 2: Channel 4's real source page turns into an AGMM-illustrative callback interlock.
   Native crops are referenced by authenticated hosted paths; never read or staged on this Mac. */
(function () {
  var css = document.createElement('style');
  css.textContent = [
    '.s90-stage{position:absolute;inset:0;overflow:hidden;background:#081827;color:#f6f2e8;font-family:"AG Plex Mono",monospace}',
    '.s90-halo{position:absolute;left:50%;top:47%;width:1220px;height:1220px;margin:-610px 0 0 -610px;border:2px solid rgba(92,198,206,.24);border-radius:50%;box-shadow:0 0 0 42px rgba(92,198,206,.04),0 0 0 120px rgba(92,198,206,.025)}',
    '.s90-ruler{position:absolute;width:9px;background:#f2b84b;box-shadow:0 0 24px rgba(242,184,75,.28);transform-origin:50% 0}',
    '.s90-source{position:absolute;left:46px;top:204px;width:988px;height:1120px;box-sizing:border-box;background:#fbfaf6;color:#14212c;border:8px solid #e4e2da;box-shadow:0 36px 80px rgba(0,0,0,.48);overflow:hidden}',
    '.s90-source-quote{position:absolute;left:54px;top:188px;width:972px;height:1080px;box-sizing:border-box;background:#fbfaf6;color:#14212c;border:8px solid #e4e2da;box-shadow:0 36px 80px rgba(0,0,0,.48);overflow:hidden}',
    '.s90-source-quote-head{position:absolute;left:28px;right:28px;top:22px;height:112px;display:flex;align-items:center;justify-content:center;background:#fff;border-bottom:3px solid #1b2934}',
    '.s90-source-quote-head img{width:100%;height:100%;object-fit:contain}',
    '.s90-source-quote-date{position:absolute;left:34px;top:152px;width:360px;height:64px;object-fit:contain;object-position:left center;background:#fff}',
    '.s90-source-quote-label{position:absolute;left:42px;right:42px;top:248px;height:70px;color:#234452;font:800 42px/1.05 "AG Plex Mono",monospace;letter-spacing:.015em;white-space:nowrap;overflow:hidden;border-top:4px solid #d8d2c3;padding-top:16px;box-sizing:border-box}',
    '.s90-source-quote-copy{position:absolute;left:62px;right:62px;top:356px;height:560px;display:flex;align-items:center;justify-content:center;text-align:left;font-family:"AG Archivo",sans-serif;font-weight:800;line-height:1.02;letter-spacing:-.035em;color:#14212c;white-space:normal}',
    '.s90-source-quote-copy.center{text-align:center}',
    '.s90-source-quote-copy.short{font-weight:900;letter-spacing:-.045em}',
    '.s90-source-quote-credit{position:absolute;left:0;right:0;bottom:0;min-height:132px;display:flex;align-items:center;padding:14px 22px;box-sizing:border-box;background:#14212c;color:#fff;font:800 42px/1.08 "AG Plex Mono",monospace;z-index:8}',
    '.s90-head{position:absolute;left:24px;right:24px;top:22px;height:112px;overflow:hidden;display:flex;align-items:center;justify-content:center;background:#fff;border-bottom:3px solid #1b2934}',
    '.s90-head img{max-width:100%;max-height:100%;object-fit:contain}',
    '.s90-title{position:absolute;left:30px;right:30px;top:150px;height:160px;overflow:hidden;background:#fff}',
    '.s90-title img{width:100%;height:100%;object-fit:contain}',
    '.s90-date{position:absolute;left:30px;right:30px;top:328px;height:88px;overflow:hidden;background:#fff}',
    '.s90-date img{width:100%;height:100%;object-fit:contain}',
    '.s90-excerpt{position:absolute;left:30px;right:30px;top:442px;height:570px;overflow:hidden;background:#fff;border:2px solid #c8c8c0;display:flex;align-items:center;justify-content:center;}',
    '.s90-excerpt img{display:block;width:100%;height:100%;max-width:100%;max-height:100%;object-fit:contain;object-position:center;transform:none;}',
    '.s90-credit{position:absolute;left:22px;right:22px;bottom:0;min-height:96px;display:flex;align-items:center;padding:4px 14px;box-sizing:border-box;background:#14212c;color:#fff;font-size:42px;line-height:1.05;letter-spacing:-.02em;z-index:8}',
    '.s90-paperlabel{position:absolute;font-size:42px;line-height:1.08;font-weight:700;letter-spacing:.025em}',
    '.s90-hero{position:absolute;left:58px;right:58px;top:56px;font-family:"AG Archivo",sans-serif;font-size:116px;line-height:.92;font-weight:900;letter-spacing:-.045em;color:#fff}',
    '.s90-hero em{font-style:normal;color:#f2b84b}',
    '.s90-sub{position:absolute;font-size:48px;line-height:1.05;font-weight:700;color:#b8dfe0}',
    '.s90-aperture{position:absolute;width:370px;height:370px;border:12px solid #a8d4d8;border-radius:50%;box-shadow:inset 0 0 0 16px #081827,0 0 0 20px rgba(168,212,216,.15);background:#06111b;box-sizing:border-box;overflow:visible}',
    '.s90-aperture:before,.s90-aperture:after{content:"";position:absolute;left:50%;top:50%;background:#f2b84b;opacity:.75;transform:translate(-50%,-50%)}',
    '.s90-aperture:before{width:3px;height:110%}.s90-aperture:after{height:3px;width:110%}',
    '.s90-rail{position:absolute;height:104px;border:4px solid #97c8cc;background:linear-gradient(90deg,rgba(18,51,68,.97),rgba(31,80,91,.92));box-shadow:12px 14px 0 rgba(0,0,0,.3);display:flex;align-items:center;justify-content:center;padding:0 10px;box-sizing:border-box;font-size:42px;font-weight:800;letter-spacing:.02em;color:#fff;white-space:nowrap;overflow:hidden}',
    '.s90-strip{position:absolute;width:1180px;height:110px;border-top:16px solid #e7c782;border-bottom:16px solid #e7c782;background:repeating-linear-gradient(90deg,#132333 0 58px,#e7c782 58px 74px);box-shadow:0 18px 0 rgba(0,0,0,.25);box-sizing:border-box}',
    '.s90-quote{position:absolute;left:64px;right:64px;top:1210px;min-height:170px;padding:24px 32px;background:#f6f2e8;color:#172431;border-left:12px solid #f2b84b;font-family:"AG Source Serif",serif;font-size:48px;line-height:1.12;box-shadow:14px 18px 0 rgba(0,0,0,.22)}',
    '.s90-tile{position:absolute;width:390px;height:280px;border:5px solid #b8dfe0;background:#f5f1e7;color:#172431;box-shadow:14px 18px 0 rgba(0,0,0,.33);box-sizing:border-box}',
    '.s90-tile-hd{position:absolute;left:0;right:0;top:0;height:66px;background:#163044;color:#fff;padding:12px 18px;font-size:42px;font-weight:800;box-sizing:border-box}',
    '.s90-tile-body{position:absolute;left:22px;right:22px;top:92px;font-size:44px;line-height:1.1;font-weight:700}',
    '.s90-request{position:absolute;left:74px;top:690px;width:850px;height:324px;background:#f5f1e7;border:8px solid #d9d4c8;box-shadow:22px 26px 0 rgba(0,0,0,.32);color:#172431;box-sizing:border-box}',
    '.s90-request-top{position:absolute;left:0;right:0;top:0;height:68px;padding:12px 24px;background:#19394a;color:#fff;font-size:42px;font-weight:800;box-sizing:border-box}',
    '.s90-request-row{position:absolute;left:26px;right:26px;top:110px;height:72px;border-bottom:3px solid #c8c1b4;font-size:42px;display:flex;align-items:center;justify-content:space-between}',
    '.s90-latch{position:absolute;left:332px;top:1040px;width:416px;height:220px;border:10px solid #e1b34c;border-radius:24px;background:#172b38;box-shadow:0 0 0 16px rgba(225,179,76,.12),18px 22px 0 rgba(0,0,0,.35)}',
    '.s90-latch:before{content:"";position:absolute;left:122px;top:-124px;width:150px;height:154px;border:18px solid #e1b34c;border-bottom:0;border-radius:100px 100px 0 0}',
    '.s90-latch-mark{position:absolute;left:0;right:0;top:74px;text-align:center;font-size:48px;font-weight:900;color:#f5e4ba}',
    '.s90-route{position:absolute;height:10px;background:#55c6be;transform-origin:left center;box-shadow:0 0 18px rgba(85,198,190,.4)}',
    '.s90-blocked{position:absolute;height:10px;background:#d34a43;opacity:.9;transform-origin:left center}',
    '.s90-phone{position:absolute;width:170px;height:290px;border:10px solid #d7e2df;border-radius:30px;background:#172d3c;box-shadow:14px 20px 0 rgba(0,0,0,.35)}',
    '.s90-phone:before{content:"";position:absolute;left:48px;right:48px;top:18px;height:10px;border-radius:8px;background:#d7e2df}',
    '.s90-phone:after{content:"";position:absolute;left:61px;bottom:16px;width:28px;height:28px;border:4px solid #d7e2df;border-radius:50%}',
    '.s90-rule{position:absolute;left:64px;right:64px;top:220px;min-height:228px;display:flex;align-items:center;justify-content:center;text-align:center;background:#f2b84b;color:#132331;border:8px solid #fff0bd;box-shadow:16px 20px 0 rgba(0,0,0,.34);font-family:"AG Archivo",sans-serif;font-size:65px;line-height:1.03;font-weight:900;padding:26px;box-sizing:border-box}',
    '.s90-pending{position:absolute;left:120px;right:120px;top:1450px;text-align:center;color:#f2b84b;font-size:48px;font-weight:900;letter-spacing:.08em}',
    '.s90-cta{position:absolute;left:58px;right:58px;top:470px;text-align:center;font-family:"AG Archivo",sans-serif;font-size:78px;line-height:1.04;font-weight:900;color:#fff}',
    '.s90-link{position:absolute;left:46px;right:46px;top:1170px;height:152px;display:flex;align-items:center;justify-content:center;background:#f2b84b;color:#102332;border:8px solid #fff0bd;box-shadow:16px 20px 0 rgba(0,0,0,.34);font-size:46px;font-weight:900;white-space:nowrap}',
    '.s90-tag{position:absolute;left:70px;top:690px;padding:10px 18px;background:#fff;color:#122634;font-size:42px;font-weight:900;letter-spacing:.08em}',
    '.s90-glass{position:absolute;border:5px solid rgba(185,228,229,.9);background:linear-gradient(135deg,rgba(185,228,229,.18),rgba(21,64,82,.42));box-shadow:9px 12px 0 rgba(0,0,0,.24)}',
    '.s90-needle{position:absolute;left:82px;right:82px;height:4px;background:#efbd58;box-shadow:0 0 16px #efbd58;transform-origin:left center}',
    '.s90-punch{position:absolute;width:36px;height:36px;border-radius:50%;background:#efbd58;box-shadow:0 0 0 10px rgba(239,189,88,.18)}',
    '.s90-caption-hero{position:absolute;left:54px;right:54px;top:140px;text-align:center;font-family:"AG Archivo",sans-serif;font-size:106px;line-height:.95;font-weight:900;color:#fff}',
    '.s90-micro{position:absolute;font-size:42px;line-height:1.05;font-weight:800;letter-spacing:.06em;color:#c4dddf}',
    '.s90-turn{position:absolute;left:0;top:0;width:100%;height:100%;background:linear-gradient(145deg,#0a2131,#102e3c 58%,#081827)}',
    '.ag-stage .ag2-cap{top:1360px!important;height:280px!important;z-index:60}',
    '.ag-stage .ag2-card{align-items:center}',
    '[data-look="softui"] .ag2-card .row{color:#102332!important;background:#f5f1e7;border:4px solid #f2b84b;border-radius:10px;padding:12px 24px 16px;box-shadow:0 12px 0 rgba(0,0,0,.35)}',
    '[data-look="softui"] .ag2-w.emph{background:#f2b84b!important;color:#102332!important;padding:5px 18px 9px;border-radius:4px}'
  ].join('\n');
  document.head.appendChild(css);
  var A = window.AGK = window.AGK || {}; A.scenes = A.scenes || {};
  var SOURCE_CROP_DIMS = {
    'claim-01.png':[1230,418], 'claim-03.png':[1230,262], 'claim-04.png':[1230,106],
    'claim-05.png':[1230,210], 'claim-06.png':[1230,262], 'claim-07.png':[1230,366],
    'claim-08.png':[1230,106]
  };
  function el(tag, cls, parent, html) { return AG.el(tag, cls, parent, html); }
  function pos(e,x,y,w,h) { e.style.left=x+'px'; e.style.top=y+'px'; if(w!=null)e.style.width=w+'px'; if(h!=null)e.style.height=h+'px'; return e; }
  function text(parent, cls, value, x,y,w,h,size) { var e=el('div',cls,parent); e.textContent=value; pos(e,x,y,w,h); if(size)e.style.fontSize=size+'px'; return e; }
  function stage(ctx,S,B) {
    // AG.scene owns the beat interval. A second child opacity pair at t=0 blanks the hook on initial seek.
    return el('div','s90-stage',S.cam);
  }
  function enter(ctx,e,t,from,dur,ease) { ctx.tl.fromTo(e,from,{x:0,y:0,rotation:0,scale:1,opacity:1,duration:dur||0.32,ease:ease||'power3.out',immediateRender:false},t); }
  function sourcePane(ctx,L,crop,at,variant) {
    var g=Object.assign({x:24,y:220,w:1032,headY:22,headH:112,titleY:150,titleH:160,dateY:328,dateH:88,excerptY:442},variant||{});
    var dims=SOURCE_CROP_DIMS[crop]; if(!dims) throw new Error('unbound source crop '+crop);
    g.excerptH=Math.ceil((g.w-60)*dims[1]/dims[0]);
    g.h=g.excerptY+g.excerptH+132;
    var pane=el('div','s90-source',L); pos(pane,g.x,g.y,g.w,g.h);
    var head=el('div','s90-head',pane), hi=el('img','',head); hi.src='img/s90-source-pack/header-channel4.png'; pos(head,24,g.headY,g.w-48,g.headH);
    var title=el('div','s90-title',pane), ti=el('img','',title); ti.src='img/s90-source-pack/release-title.png'; pos(title,30,g.titleY,g.w-60,g.titleH);
    var date=el('div','s90-date',pane), di=el('img','',date); di.src='img/s90-source-pack/release-date.png'; pos(date,30,g.dateY,g.w-60,g.dateH);
    var win=el('div','s90-excerpt',pane), im=el('img','',win); im.src='img/s90-source-pack/'+crop; pos(win,30,g.excerptY,g.w-60,g.excerptH);
    // Keep every source word in the native crop. The hosted Linux preview must establish its actual readable size.
    im.style.width='100%'; im.style.height='100%'; im.style.maxWidth='100%'; im.style.maxHeight='100%'; im.style.objectFit='contain'; im.style.objectPosition='center';
    var cr=el('div','s90-credit',pane,'Source: Channel 4, News Release, 20 October 2025'); cr.style.fontSize='42px';
    return {pane:pane,window:win,img:im,credit:cr,header:head,title:title,date:date};
  }
  function hero(parent,html,x,y,size) { var e=el('div','s90-hero',parent,html); pos(e,x,y); e.style.fontSize=size+'px'; return e; }
  function rails(ctx,L,at) {
    var rows=[]; ['FACE','VOICE','MOVEMENTS'].forEach(function(label,i){ var r=el('div','s90-rail',L,label); r.style.right='auto'; pos(r,62+i*320,76,294,104); enter(ctx,r,at+i*.18,{y:-150,rotation:2,opacity:0},.26,'power3.out'); rows.push(r); }); return rows;
  }
  function glass(ctx,L,x,y,w,h,at,rot) { var g=el('div','s90-glass',L); pos(g,x,y,w,h); g.style.transform='rotate('+(rot||0)+'deg)'; enter(ctx,g,at,{y:-260,rotation:(rot||0)-5,opacity:0},.36,'power3.out'); return g; }
  function sourceTarget(ctx,L,crop,at,layout) {
    return sourcePane(ctx,L,crop,at,layout||{});
  }
  function sourceQuote(ctx,L,copy,variant) {
    var g=Object.assign({x:54,y:188,w:972,h:980,size:76,align:'left',label:'SOURCE QUOTATION'},variant||{});
    var pane=el('div','s90-source-quote',L); pos(pane,g.x,g.y,g.w,g.h);
    var head=el('div','s90-source-quote-head',pane), logo=el('img','',head); pos(head,28,22,g.w-56,112); logo.src='img/s90-source-pack/header-channel4.png';
    var date=el('img','s90-source-quote-date',pane); pos(date,34,152,g.w-68,64); date.src='img/s90-source-pack/release-date.png';
    text(pane,'s90-source-quote-label',g.label,42,248,g.w-84,70,42);
    var body=text(pane,'s90-source-quote-copy '+(g.align==='center'?'center ':'')+(g.size>=88?'short':''),copy,62,356,g.w-124,480,g.size);
    var credit=el('div','s90-source-quote-credit',pane,'Source: Channel 4, News Release, 20 October 2025');
    pos(credit,0,g.h-132,g.w,132);
    return {pane:pane,body:body,header:head,date:date,credit:credit};
  }
  function captionPlate(L,copy,x,y,w,h,size) { var e=el('div','s90-rule',L); e.textContent=copy; pos(e,x,y,w,h); e.style.fontSize=size+'px'; return e; }
  function lightHit(ctx,e,t) { ctx.tl.fromTo(e,{scale:.72,opacity:.35},{scale:1,opacity:1,duration:.18,ease:'power3.out',immediateRender:false},t); }
  function request(ctx,L,at,state) {
    var r=el('div','s90-request',L); var hd=el('div','s90-request-top',r,'ILLUSTRATION / SUPPLIER CHANGE');
    pos(r,74,690,850,324); pos(hd,0,0,850,68);
    var a=el('div','s90-request-row',r); a.innerHTML='<span>REQUEST</span><b>Bank details</b>';
    pos(a,26,110,798,72);
    var b=el('div','s90-request-row',r); pos(b,26,192,798,72); b.innerHTML='<span>STATE</span><b>'+(state||'PENDING')+'</b>'; b.querySelector('b').style.color='#a53e35';
    // The request and PENDING state are already readable at the incoming cut; only the rail gets a restrained settle.
    ctx.tl.fromTo(r,{rotation:-0.4},{rotation:0,duration:.16,ease:'power2.out',immediateRender:false},at); return r;
  }
  function latch(ctx,L,at) {
    var x=el('div','s90-latch',L), m=el('div','s90-latch-mark',x,'PAYMENT HELD');
    pos(x,332,1040,416,220); pos(m,0,74,416,68);
    // Keep the latch and PAYMENT HELD legible from the cut; animate only the lock mark.
    ctx.tl.fromTo(m,{scale:.96,opacity:.8},{scale:1,opacity:1,duration:.2,ease:'power2.out',immediateRender:false},at);
    return x;
  }

  // 01 · full source identity and the empty optical gate are already present on frame zero.
  A.scenes['s90-b01']=function(ctx,S,p,B){
    var L=stage(ctx,S,B); el('div','s90-halo',L);
    var sp=sourcePane(ctx,L,'claim-01.png',B.from,{x:46,y:204,w:988,h:1120});
    var aperture=el('div','s90-aperture',L); pos(aperture,812,10,190,190);
    var h=hero(L,'CHANNEL 4<br><em>AI PRESENTER</em>',68,34,86);
    var mark=el('div','s90-ruler',L); pos(mark,28,210,8,1118);
    ctx.tl.fromTo(mark,{scaleY:.25,transformOrigin:'50% 0%'},{scaleY:1,duration:2.1,ease:'power1.inOut',immediateRender:false},B.from+.22);
    return L;
  };
  // 02 · a large exact source quotation replaces the repeated full-page headline; attribution stays visible.
  A.scenes['s90-b02']=function(ctx,S,p,B){
    var L=stage(ctx,S,B); el('div','s90-turn',L);
    sourceQuote(ctx,L,"Because I'm not real.",{size:112,align:'center',label:'PRESENTER · SOURCE QUOTATION'});
    return L;
  };
  // 03 · the source's exact face/voice/movements wording becomes the evidence hierarchy.
  A.scenes['s90-b03']=function(ctx,S,p,B){
    var L=stage(ctx,S,B); sourceQuote(ctx,L,'their face, voice and movements all created through AI technology',{size:72,label:'SOURCE QUOTATION · CLAIM 03'});
    return L;
  };
  // 04 · the exact “without a single frame” proof line takes the full reading field.
  A.scenes['s90-b04']=function(ctx,S,p,B){
    var L=stage(ctx,S,B); sourceQuote(ctx,L,'without a single frame of real-world filming',{size:88,align:'center',label:'SOURCE QUOTATION · CLAIM 03'});
    return L;
  };
  // 05 · reveal only the first exact clause; B06 carries the exact continuation.
  A.scenes['s90-b05']=function(ctx,S,p,B){
    var L=stage(ctx,S,B); sourceQuote(ctx,L,'Some of you might have guessed:',{size:90,label:'PRESENTER · SOURCE QUOTATION'});
    return L;
  };
  // 06 · the verbatim continuation answers the setup; no presenter image or reconstructed footage.
  A.scenes['s90-b06']=function(ctx,S,p,B){
    var L=stage(ctx,S,B); sourceQuote(ctx,L,"I don't exist, I wasn't on location reporting this story.",{size:76,label:'PRESENTER · SOURCE QUOTATION'});
    return L;
  };
  // 07 · show the source's exact stunt description as a legible quotation.
  A.scenes['s90-b07']=function(ctx,S,p,B){
    var L=stage(ctx,S,B); sourceQuote(ctx,L,'as part of a deliberate on-screen stunt to show just how convincing artificial intelligence has become',{size:62,label:'SOURCE QUOTATION · CLAIM 06'});
    return L;
  };
  // 08 · the exact speaker introduction is typeset as a quotation, not compressed beneath the repeated headline.
  A.scenes['s90-b08']=function(ctx,S,p,B){
    var L=stage(ctx,S,B); sourceQuote(ctx,L,'Louisa Compton, Head of News and Current Affairs, Specialist Factual and Sport at Channel 4, said:',{size:54,label:'SOURCE QUOTATION · ATTRIBUTION'});
    return L;
  };
  // 09 · Compton's first exact warning fragment becomes the new claim hierarchy.
  A.scenes['s90-b09']=function(ctx,S,p,B){
    var L=stage(ctx,S,B); sourceQuote(ctx,L,'how easy it is to hoodwink audiences',{size:82,label:'COMPTON · SOURCE QUOTATION'});
    return L;
  };
  // 10 · the exact continuation completes the warning, then the publisher material exits at the next cut.
  A.scenes['s90-b10']=function(ctx,S,p,B){
    var L=stage(ctx,S,B); sourceQuote(ctx,L,'with content they have no way of verifying',{size:78,label:'COMPTON · SOURCE QUOTATION'});
    return L;
  };
  // 11 · all publisher marks and credits are gone before the accounts advice begins.
  A.scenes['s90-b11']=function(ctx,S,p,B){var L=stage(ctx,S,B); el('div','s90-turn',L); var tag=text(L,'s90-tag','ILLUSTRATION',72,142,490,72,44); request(ctx,L,B.from+.16); var tile=el('div','s90-tile',L); pos(tile,616,430,376,242); tile.innerHTML='<div class="s90-tile-hd">ACCOUNTS TEAM</div><div class="s90-tile-body">VIDEO CALL<br>SUPPLIER</div>'; ctx.tl.fromTo(tile,{rotation:1.5},{rotation:0,duration:.2,ease:'power2.out',immediateRender:false},B.from); var r=latch(ctx,L,B.from+.62); return L;};
  // 12 · the principle becomes a physical rule plate beside the still-pending request.
  A.scenes['s90-b12']=function(ctx,S,p,B){var L=stage(ctx,S,B); el('div','s90-turn',L); request(ctx,L,B.from+.04); latch(ctx,L,B.from+.16); var plate=captionPlate(L,'ONE RULE\nTHIS WEEK',68,276,944,300,82); ctx.tl.fromTo(plate,{rotation:-2},{rotation:0,duration:.24,ease:'power2.out',immediateRender:false},B.from); var rivet=el('div','s90-punch',L); pos(rivet,900,600); lightHit(ctx,rivet,B.from+.55); return L;};
  // 13 · an unapproved change request stays blank of identity, amount, and account data.
  A.scenes['s90-b13']=function(ctx,S,p,B){var L=stage(ctx,S,B); el('div','s90-turn',L); request(ctx,L,B.from+.05); var x=latch(ctx,L,B.from+.2); var pending=text(L,'s90-pending','PENDING CHANGE',180,610,720,72,48); var slip=el('div','s90-paperlabel',L,'BANK-DETAIL CHANGE'); pos(slip,112,502,850,90); ctx.tl.fromTo(slip,{rotation:-1.5},{rotation:0,duration:.18,ease:'power2.out',immediateRender:false},B.from); var dot=el('div','s90-punch',L); pos(dot,853,826); lightHit(ctx,dot,B.from+.58); return L;};
  // 14 · trusted-number path places an outgoing call; the payment latch explicitly stays shut.
  A.scenes['s90-b14']=function(ctx,S,p,B){var L=stage(ctx,S,B); el('div','s90-turn',L); request(ctx,L,B.from+.03,'CALL STARTED'); latch(ctx,L,B.from+.1); var saved=el('div','s90-tile',L); pos(saved,76,394,444,230); saved.innerHTML='<div class="s90-tile-hd">SAVED CONTACT</div><div class="s90-tile-body">NUMBER<br>ALREADY HELD</div>'; ctx.tl.fromTo(saved,{rotation:-1},{rotation:0,duration:.18,ease:'power2.out',immediateRender:false},B.from); var ph=el('div','s90-phone',L); pos(ph,742,394); ctx.tl.fromTo(ph,{rotation:8},{rotation:0,duration:.3,ease:'power2.out',immediateRender:false},B.from); var route=el('div','s90-route',L); pos(route,468,700,300,10); ctx.tl.fromTo(route,{scaleX:0},{scaleX:1,duration:.45,ease:'power2.out',immediateRender:false},B.from+.76);  return L;};
  // 15 · the message path is physically disconnected; no successful confirmation is depicted.
  A.scenes['s90-b15']=function(ctx,S,p,B){var L=stage(ctx,S,B); el('div','s90-turn',L); request(ctx,L,B.from+.02,'NO ANSWER'); latch(ctx,L,B.from+.08); var saved=el('div','s90-tile',L); pos(saved,62,356,410,226); saved.innerHTML='<div class="s90-tile-hd">HELD CONTACT</div><div class="s90-tile-body">KNOWN ROUTE</div>'; var msg=el('div','s90-tile',L); pos(msg,608,356,410,226); msg.innerHTML='<div class="s90-tile-hd">MESSAGE</div><div class="s90-tile-body">NEW NUMBER</div>'; ctx.tl.fromTo(msg,{rotation:1},{rotation:0,duration:.18,ease:'power2.out',immediateRender:false},B.from); var ok=el('div','s90-route',L); pos(ok,454,680,280,9); var bad=el('div','s90-blocked',L); pos(bad,812,582,8,170); bad.style.transform='rotate(34deg)'; return L;};
  // 16 · CTA only; no Channel 4 brand, evidence pane, call answer, or latch release.
  A.scenes['s90-b16']=function(ctx,S,p,B){var L=stage(ctx,S,B); el('div','s90-turn',L); var halo=el('div','s90-halo',L); halo.style.borderColor='rgba(242,184,75,.35)'; var tx=el('div','s90-cta',L,'FOLLOW FOR ONE REAL AI STORY A DAY,<br>AND WHAT IT MEANS FOR YOUR BUSINESS'); pos(tx,50,500,980,440); ctx.tl.fromTo(tx,{y:16},{y:0,duration:.22,ease:'power2.out',immediateRender:false},B.from); var pend=text(L,'s90-pending','CHANGE REMAINS PENDING UNTIL CONFIRMED',62,1030,956,82,42); var link=el('div','s90-link',L,'agmm.co.uk/ai-constraint-audit');pos(link,46,1134,988,152);ctx.tl.fromTo(link,{scale:.98},{scale:1,duration:.2,ease:'power2.out',immediateRender:false},B.from+.08); return L;};
  // Native kit3 adapter: scene-only component; the selected S90 scene owns each beat.
  A.C=A.C||{};
  A.C['s90-custom']=function(ctx,S,props,B){
    var render=A.scenes[props.scene];
    if(!render) throw new Error('unknown S90 scene '+String(props.scene));
    render(ctx,S,props,B);
  };
})();
