/* S81 narrative picture correction. Source text and claims stay bound to the locked script. */
(function () {
  var C = { ink: "#122032", ink2: "#1c3044", paper: "#f4f0e7", white: "#fffdf7", red: "#c52c35", blue: "#2f5aa4", teal: "#7bc6ba", grey: "#d7d4cc", muted: "#bfc5c8" };
  var css = document.createElement("style");
  css.textContent = [
    ".s81-root{position:absolute;inset:0;overflow:hidden;background:"+C.ink+";color:"+C.paper+";font-family:'AG2 Instrument Sans',sans-serif}",
    ".s81-root:before{content:'';position:absolute;inset:0;background-image:radial-gradient(rgba(244,240,231,.11) .8px,transparent 1px);background-size:18px 18px;opacity:.36}",
    ".s81-world{position:absolute;inset:0;overflow:hidden}",
    ".s81-kicker{position:absolute;left:64px;right:246px;top:48px;font:700 42px/1.08 'AG2 Red Hat Mono',monospace;letter-spacing:.04em;text-transform:uppercase;color:"+C.teal+"}",
    ".s81-credit{position:absolute;left:64px;right:64px;bottom:20px;height:220px;box-sizing:border-box;border-top:2px solid rgba(244,240,231,.7);padding-top:16px;font:700 42px/1.08 'AG2 Red Hat Mono',monospace;color:"+C.paper+";overflow-wrap:anywhere}",
    ".s81-mark{position:absolute;right:66px;top:48px;width:148px;height:148px;object-fit:contain;background:"+C.paper+";padding:18px;border-radius:50%;box-sizing:border-box;filter:drop-shadow(0 4px 0 rgba(0,0,0,.15))}",
    ".s81-title{position:absolute;left:64px;right:64px;top:190px;font:700 124px/.9 'AG2 Bricolage',sans-serif;letter-spacing:-.045em;text-transform:uppercase;white-space:pre-line}",
    ".s81-small{font:700 42px/1.12 'AG2 Red Hat Mono',monospace;letter-spacing:.02em;text-transform:uppercase}",
    ".s81-portal{position:absolute;left:50%;margin-left:-340px;top:420px;width:680px;height:660px;border:18px solid "+C.teal+";border-radius:360px 360px 12px 12px;background:linear-gradient(90deg,"+C.ink2+" 0 48%,"+C.red+" 48% 50%,"+C.ink2+" 50%);box-shadow:0 0 0 22px rgba(123,198,186,.13),0 40px 100px rgba(0,0,0,.4);box-sizing:border-box}",
    ".s81-portal:before{content:'';position:absolute;inset:46px 40px 0;border:4px solid rgba(244,240,231,.54);border-bottom:0;border-radius:315px 315px 0 0}",
    ".s81-portal:after{content:'';position:absolute;left:50%;top:42%;height:44%;border-left:5px dashed "+C.red+"}",
    ".s81-portallabel{position:absolute;left:0;right:0;top:48%;text-align:center;font:700 42px/1.1 'AG2 Red Hat Mono',monospace;color:"+C.white+";text-shadow:0 3px 16px #000;white-space:pre-line}",
    ".s81-gateway-tag{position:absolute;left:50%;top:1110px;transform:translateX(-50%);padding:14px 22px;border:3px solid "+C.red+";background:"+C.ink+";font:700 42px/1.08 'AG2 Red Hat Mono',monospace;white-space:nowrap}",
    ".s81-route{position:absolute;left:80px;right:80px;bottom:730px;height:10px;background:rgba(244,240,231,.3);transform-origin:left}",
    ".s81-route:before{content:'';position:absolute;inset:0 auto 0 0;width:var(--fill,0%);background:"+C.red+"}",
    ".s81-date{position:absolute;top:1090px;font:700 42px/1.08 'AG2 Red Hat Mono',monospace;color:"+C.paper+"}",
    ".s81-date.june{left:72px}.s81-date.sept{right:72px;text-align:right}",
    ".s81-node{position:absolute;width:64px;height:64px;border:10px solid "+C.red+";border-radius:50%;background:"+C.ink+";box-sizing:border-box;bottom:698px}",
    ".s81-node.june{left:64px}.s81-node.sept{right:64px}",
    ".s81-evidence{position:absolute;left:64px;right:64px;top:230px;bottom:760px;display:flex;align-items:center;gap:30px}",
    ".s81-boundary{position:relative;flex:0 0 32%;height:100%;border:12px solid "+C.teal+";border-radius:280px 280px 0 0;background:linear-gradient(90deg,"+C.ink2+" 0 49%,"+C.red+" 49% 51%,"+C.ink2+" 51%);box-shadow:0 24px 70px rgba(0,0,0,.32)}",
    ".s81-file{position:absolute;width:200px;height:250px;background:"+C.paper+";color:"+C.ink+";border-radius:10px;padding:18px;box-sizing:border-box;box-shadow:0 16px 26px rgba(0,0,0,.32);font:700 42px/1.08 'AG2 Red Hat Mono',monospace;text-transform:uppercase;white-space:pre-line;overflow-wrap:anywhere}",
    ".s81-file:after{content:'';position:absolute;left:20px;right:20px;bottom:32px;height:6px;background:"+C.red+";box-shadow:0 -23px 0 "+C.blue+",0 -46px 0 "+C.blue+"}",
    ".s81-file.public{left:-40px;top:38%}.s81-file.private{right:-40px;bottom:10%}",
    ".s81-quote{flex:1;font:700 50px/1.12 'AG2 Instrument Sans',sans-serif;letter-spacing:-.025em;color:"+C.paper+"}",
    ".s81-quote em{font-style:normal;color:"+C.teal+"}",
    ".s81-evaluation{position:absolute;left:64px;right:64px;top:300px;bottom:760px;border:10px solid "+C.teal+";border-radius:28px;background:"+C.ink2+";box-shadow:0 28px 0 rgba(0,0,0,.25);overflow:hidden}",
    ".s81-evaluation:before{content:'';position:absolute;left:0;right:0;top:100px;border-top:6px solid "+C.red+"}",
    ".s81-monitorbar{position:absolute;left:36px;right:36px;top:32px;display:flex;justify-content:space-between;color:"+C.teal+"}",
    ".s81-search{position:absolute;left:50px;top:175px;width:320px;height:320px;border:18px solid "+C.red+";border-radius:50%;box-sizing:border-box;box-shadow:inset 0 0 0 18px rgba(197,44,53,.1)}",
    ".s81-search:after{content:'';position:absolute;right:-170px;bottom:-110px;width:210px;border-top:24px solid "+C.red+";transform:rotate(47deg);transform-origin:left}",
    ".s81-au{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font:700 116px 'AG2 Bricolage',sans-serif;color:"+C.paper+"}",
    ".s81-evalcopy{position:absolute;left:470px;right:44px;top:190px;font:700 47px/1.15 'AG2 Instrument Sans',sans-serif}",
    ".s81-statement{position:absolute;left:64px;right:64px;top:260px;bottom:760px;display:flex;flex-direction:column;justify-content:center}",
    ".s81-quote-mark{position:absolute;left:-8px;top:-5px;font:700 300px/.8 'AG2 Bricolage',sans-serif;color:"+C.red+"}",
    ".s81-statement-text{position:relative;margin:70px 0 0 40px;font:700 82px/.98 'AG2 Bricolage',sans-serif;letter-spacing:-.04em;color:"+C.paper+"}",
    ".s81-statement-by{margin:42px 0 0 44px;font:700 42px/1.08 'AG2 Red Hat Mono',monospace;color:"+C.teal+"}",
    ".s81-calendar{position:absolute;left:64px;right:64px;top:310px;bottom:760px;display:flex;align-items:center;justify-content:space-between;gap:24px}",
    ".s81-monthcard{position:relative;flex:1;min-width:0;height:620px;background:"+C.paper+";color:"+C.ink+";border-radius:18px;box-shadow:0 30px 0 rgba(0,0,0,.28);padding:22px;box-sizing:border-box;transform-origin:bottom center}",
    ".s81-monthcard:before{content:'';position:absolute;left:0;right:0;top:150px;border-top:8px solid "+C.red+"}",
    ".s81-monthname{max-width:100%;font:700 42px/1.02 'AG2 Red Hat Mono',monospace;color:"+C.blue+";text-transform:uppercase;overflow-wrap:anywhere}",
    ".s81-monthnumber{position:absolute;left:22px;top:178px;font:700 118px/.9 'AG2 Bricolage',sans-serif;color:"+C.ink+"}",
    ".s81-monthnote{position:absolute;left:22px;right:20px;bottom:22px;font:700 42px/1.08 'AG2 Red Hat Mono',monospace;white-space:pre-line;overflow-wrap:anywhere}",
    ".s81-mailbox{position:absolute;left:50%;margin-left:-325px;top:420px;width:650px;height:550px;border:18px solid "+C.teal+";border-radius:22px;background:"+C.ink2+";box-shadow:0 30px 80px rgba(0,0,0,.36)}",
    ".s81-mail-slot{position:absolute;left:80px;right:80px;top:130px;height:34px;background:"+C.ink+";border:6px solid "+C.paper+";border-radius:20px}",
    ".s81-letter{position:absolute;left:50%;margin-left:-185px;top:185px;width:370px;height:330px;background:"+C.paper+";color:"+C.ink+";padding:24px;box-sizing:border-box;box-shadow:0 20px 30px rgba(0,0,0,.35)}",
    ".s81-letter:after{content:'';position:absolute;left:24px;right:24px;top:30px;height:110px;border-bottom:7px solid "+C.red+";transform:skewY(-25deg)}",
    ".s81-once{position:absolute;right:56px;top:60px;width:200px;height:200px;border:12px solid "+C.red+";border-radius:50%;display:flex;align-items:center;justify-content:center;text-align:center;font:700 42px/1.02 'AG2 Red Hat Mono',monospace;color:"+C.paper+";background:"+C.ink+"}",
    ".s81-monitorquote{position:absolute;left:64px;right:64px;top:230px;font:700 52px/1.12 'AG2 Instrument Sans',sans-serif;color:"+C.paper+"}",
    ".s81-monitorquote strong{color:"+C.teal+"}",
    ".s81-response{position:absolute;left:64px;right:64px;top:270px;bottom:760px;border-left:20px solid "+C.red+";padding:22px 0 0 46px;box-sizing:border-box}",
    ".s81-response-mark{font:700 180px/.7 'AG2 Bricolage',sans-serif;color:"+C.teal+"}",
    ".s81-response-text{position:relative;margin-top:36px;font:700 66px/1.02 'AG2 Bricolage',sans-serif;letter-spacing:-.035em;color:"+C.paper+"}",
    ".s81-response-text em{font-style:normal;color:"+C.red+"}",
    ".s81-privacy{position:absolute;left:64px;right:64px;top:240px;bottom:760px;display:grid;grid-template-columns:38% 62%;align-items:center;gap:34px}",
    ".s81-shield{position:relative;width:100%;height:680px;border:12px solid "+C.teal+";border-radius:220px 220px 290px 290px;background:"+C.ink2+";clip-path:polygon(50% 0,100% 16%,91% 72%,50% 100%,9% 72%,0 16%);box-sizing:border-box}",
    ".s81-shield:before{content:'';position:absolute;left:50%;top:30%;height:45%;border-left:8px dashed "+C.red+"}",
    ".s81-shieldword{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;padding:54px;font:700 52px/1 'AG2 Bricolage',sans-serif;color:"+C.paper+";white-space:pre-line}",
    ".s81-privacy-copy{font:700 48px/1.1 'AG2 Instrument Sans',sans-serif;color:"+C.paper+"}",
    ".s81-stage-label{display:inline-block;margin-top:24px;padding:11px 16px;border:3px solid "+C.red+";font:700 42px/1.08 'AG2 Red Hat Mono',monospace;color:"+C.teal+"}",
    ".s81-controls{position:absolute;left:64px;right:64px;top:320px;bottom:760px;display:flex;align-items:center;gap:34px}",
    ".s81-control{position:relative;flex:1;height:600px;border:8px solid "+C.teal+";border-radius:250px;background:"+C.ink2+";display:flex;flex-direction:column;justify-content:space-between;padding:34px;box-sizing:border-box;box-shadow:0 26px 0 rgba(0,0,0,.25)}",
    ".s81-control-number{font:700 42px/1.08 'AG2 Red Hat Mono',monospace;color:"+C.red+"}",
    ".s81-control-icon{width:190px;height:190px;border:16px solid "+C.paper+";border-radius:50%;align-self:center;display:flex;align-items:center;justify-content:center;font:700 60px 'AG2 Bricolage',sans-serif;color:"+C.teal+"}",
    ".s81-control-label{font:700 42px/1.02 'AG2 Bricolage',sans-serif;text-transform:uppercase;color:"+C.paper+"}",
    ".s81-link{flex:0 0 58px;height:10px;background:"+C.red+";position:relative}",
    ".s81-link:after{content:'';position:absolute;right:-2px;top:-13px;width:24px;height:24px;border-top:8px solid "+C.red+";border-right:8px solid "+C.red+";transform:rotate(45deg)}",
    ".s81-cta-world{position:absolute;inset:0;background:"+C.red+";color:"+C.ink+"}",
    ".s81-cta-rule{position:absolute;left:0;top:50%;height:22px;width:100%;background:"+C.paper+";transform-origin:left}",
    ".s81-cta-title{position:absolute;left:64px;right:64px;top:300px;font:700 112px/.9 'AG2 Bricolage',sans-serif;letter-spacing:-.045em;text-transform:uppercase;color:"+C.ink+";white-space:pre-line}",
    ".s81-cta-url{position:absolute;left:64px;right:64px;top:850px;font:700 48px/1.1 'AG2 Red Hat Mono',monospace;color:"+C.paper+";overflow-wrap:anywhere}",
    ".s81-follow{position:absolute;left:64px;bottom:760px;font:700 42px/1.08 'AG2 Red Hat Mono',monospace;text-transform:uppercase}",
    ".s81-arrow{position:absolute;right:80px;bottom:700px;width:240px;height:18px;background:"+C.ink+";transform-origin:left}",
    ".s81-arrow:after{content:'';position:absolute;right:-4px;top:-30px;width:58px;height:58px;border-top:18px solid "+C.ink+";border-right:18px solid "+C.ink+";transform:rotate(45deg)}",
    ".s81-illustration-note{position:absolute;left:64px;right:64px;top:108px;padding:12px 18px;border-left:8px solid "+C.red+";background:"+C.ink2+";font:700 42px/1.05 'AG2 Red Hat Mono',monospace;letter-spacing:.01em;text-align:left;color:"+C.paper+";box-sizing:border-box}",
    ".ag2-card .row{background:"+C.paper+"!important;color:"+C.ink+"!important;padding:16px 28px;border:3px solid "+C.teal+";border-radius:16px;box-shadow:0 12px 26px rgba(0,0,0,.45);gap:4px .28em}",
    ".ag2-card .row .ag2-w{opacity:1!important;color:"+C.ink+"!important}",
    ".ag2-card .row .ag2-w.emph{background:"+C.ink+"!important;color:"+C.paper+"!important;padding:2px 10px 4px;border-radius:8px}"
  ].join("\n");
  document.head.appendChild(css);

  var A = window.AGK = window.AGK || {};
  A.scenes = A.scenes || {};
  function el(tag, cls, parent, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    parent.appendChild(n);
    return n;
  }
  function world(root, kicker, credit) {
    var w = el("section", "s81-world", root);
    el("div", "s81-kicker", w, kicker);
    el("div", "s81-credit", w, credit);
    return w;
  }
  function logo(parent) {
    var row = (((window.S81_SRC || {}).items || {}).openaiMark || {});
    var img = el("img", "s81-mark", parent);
    img.src = row.src || "media/openai-mark.svg";
    img.alt = "OpenAI mark identifying the company discussed; no endorsement implied";
    return img;
  }
  function bar(parent, cls, text) {
    var n = el("div", cls, parent, text);
    return n;
  }
  function enter(tl, node, from, to, x, y, ease) {
    tl.set(node, { autoAlpha: 0 }, 0);
    tl.fromTo(node, { autoAlpha: 1, x: x || 0, y: y || 0 },
      { autoAlpha: 1, x: 0, y: 0, duration: .32, ease: ease || "power2.out", immediateRender: false }, from);
    tl.to(node, { autoAlpha: 0, duration: .22, ease: "power1.in" }, to - .22);
  }

  A.scenes["s81-evidence-route"] = function (ctx) {
    var S = AG.scene(ctx, "wall", 0, null, { drift: false });
    var root = el("div", "s81-root", S.cam), tl = ctx.tl;

    var hook = world(root, "JUNE · AUSTRALIA · SYSTEM ACCESS", "BBC News · 24 Sep 2026 · source headline and report");
    logo(hook);
    bar(hook, "s81-title", "OPENAI AGENT\nIN PORTAL");
    var portal = el("div", "s81-portal", hook);
    el("div", "s81-portallabel", portal, "MEDICARE\nSTATISTICS");
    var route = el("div", "s81-route", hook); route.style.setProperty("--fill", "0%");
    el("i", "s81-node june", hook); el("i", "s81-node sept", hook);
    el("div", "s81-date june", hook, "JUNE"); el("div", "s81-date sept", hook, "SEPTEMBER · EMAIL");
    tl.set(hook, { autoAlpha: 1 }, 0);
    tl.fromTo(portal, { scaleY: .86, transformOrigin: "50% 100%" }, { scaleY: 1, duration: .7, ease: "power3.out" }, 0);
    tl.fromTo(route, { "--fill": "0%" }, { "--fill": "100%", duration: 1.7, ease: "none" }, .18);
    tl.fromTo(hook.querySelector(".s81-title"), { y: 22, autoAlpha: 1 }, { y: 0, autoAlpha: 1, duration: .42, ease: "power2.out" }, 0);
    tl.fromTo(hook.querySelector(".s81-mark"), { rotation: -7, scale: .92 }, { rotation: 0, scale: 1, duration: .48, ease: "power2.out" }, 0);
    // Preserve the approved fully visible frame-zero hook; its portal, title and mark move from zero.
    tl.to(hook, { autoAlpha: 0, duration: .22, ease: "power1.in" }, 8.38);

    var breach = world(root, "BBC · ALBANESE ON THE PORTAL", "Source: BBC News · 24 Sep 2026 · bbc.com/news/articles/c6vgy0333dppo");
    var proof = el("div", "s81-evidence", breach);
    var gate = el("div", "s81-boundary", proof);
    el("div", "s81-file public", gate, "PUBLIC\nFILES");
    el("div", "s81-file private", gate, "NON-\nPUBLIC\nFILES");
    var bq = el("div", "s81-quote", proof);
    bq.textContent = "The agent ‘infiltrated’ a statistics portal containing ‘non-sensitive’ Medicare data. He said it involved ‘public and non-public files.’";
    el("div", "s81-illustration-note", breach, "RE-TYPED SOURCE WORDING · NOT A SCREENSHOT");
    tl.fromTo(gate, { scaleX: .72, transformOrigin: "50% 50%" }, { scaleX: 1, duration: .38, ease: "power2.out" }, 8.60);
    tl.fromTo(bq, { x: 70, autoAlpha: 0 }, { x: 0, autoAlpha: 1, duration: .45, ease: "power2.out" }, 8.82);
    enter(tl, breach, 8.60, 18.40, 35, 0, "power2.out");

    var context = world(root, "BBC · OPENAI'S ACCOUNT", "Source: BBC News · 24 Sep 2026 · attributed to OpenAI");
    var monitor = el("div", "s81-evaluation", context);
    var monitorbar = el("div", "s81-monitorbar s81-small", monitor);
    el("span", "", monitorbar, "INTERNAL EVALUATION");
    el("span", "", monitorbar, "AU / STATS");
    var lens = el("div", "s81-search", monitor); el("div", "s81-au", lens, "AU");
    el("div", "s81-evalcopy", monitor, "OpenAI said its models were looking up statistics about Australia during an internal evaluation.");
    tl.fromTo(lens, { rotation: -14, scale: .86, transformOrigin: "50% 50%" }, { rotation: 0, scale: 1, duration: .55, ease: "power2.out" }, 18.40);
    tl.fromTo(monitor.querySelector(".s81-evalcopy"), { x: 72, autoAlpha: 0 }, { x: 0, autoAlpha: 1, duration: .4, ease: "power2.out" }, 18.66);
    enter(tl, context, 18.40, 24.667, 0, 40, "power2.out");

    var statement = world(root, "BBC · OPENAI STATEMENT", "Source: OpenAI statement quoted by BBC News · 24 Sep 2026");
    var quote = el("div", "s81-statement", statement);
    el("div", "s81-quote-mark", quote, "“");
    el("div", "s81-statement-text", quote, "In the course of that, our models took actions we did not intend.");
    el("div", "s81-statement-by", quote, "OPENAI STATEMENT · QUOTED BY BBC NEWS");
    tl.fromTo(quote.querySelector(".s81-statement-text"), { scale: .94, transformOrigin: "0 50%" }, { scale: 1, duration: .4, ease: "power2.out" }, 24.667);
    enter(tl, statement, 24.667, 29.20, -30, 0, "power2.out");

    var timeline = world(root, "THE NOTIFICATION ROUTE", "Source: BBC News · dates and wording attributed in the report");
    var months = el("div", "s81-calendar", timeline);
    var m1 = el("div", "s81-monthcard", months); el("div", "s81-monthname", m1, "PORTAL ACTIVITY"); el("div", "s81-monthnumber", m1, "JUN"); el("div", "s81-monthnote", m1, "JUNE\nPORTAL ACTIVITY");
    var m2 = el("div", "s81-monthcard", months); el("div", "s81-monthname", m2, "DISCOVERY"); el("div", "s81-monthnumber", m2, "AUG"); el("div", "s81-monthnote", m2, "AUGUST\nOPENAI SAYS IT FOUND OUT");
    var m3 = el("div", "s81-monthcard", months); el("div", "s81-monthname", m3, "EMAIL NOTICE"); el("div", "s81-monthnumber", m3, "10"); el("div", "s81-monthnote", m3, "10 SEPTEMBER\nEMAIL TO A GOVERNMENT ADDRESS");
    [m1,m2,m3].forEach(function (m, i) { tl.fromTo(m, { y: 100, rotation: i === 1 ? -5 : 4, autoAlpha: 0 }, { y: 0, rotation: 0, autoAlpha: 1, duration: .28, ease: "back.out(1.02)" }, 29.2 + i * .24); });
    enter(tl, timeline, 29.20, 34.50, 0, 32, "power2.out");

    var guardian = world(root, "THE GUARDIAN · THE INBOX", "Source: The Guardian · 24 Sep 2026 · technology/2026/sep/24/openai-agent-hacked-medicare-australia-what-we-know-so-far-ntwnfb");
    var mailbox = el("div", "s81-mailbox", guardian);
    el("div", "s81-mail-slot", mailbox);
    var letter = el("div", "s81-letter", mailbox);
    el("div", "s81-once", guardian, "MONITORED\nONCE A DAY");
    var monitorquote = el("div", "s81-monitorquote", guardian);
    monitorquote.appendChild(document.createTextNode("The general Australian government email address "));
    el("strong", "", monitorquote, "“is monitored once a day.”");
    tl.fromTo(letter, { y: -150, rotation: -5 }, { y: 0, rotation: 0, duration: .48, ease: "bounce.out" }, 34.50);
    tl.fromTo(guardian.querySelector(".s81-once"), { scale: .72 }, { scale: 1, duration: .32, ease: "back.out(1.1)" }, 34.86);
    enter(tl, guardian, 34.50, 37.753, 0, 28, "power2.out");

    var consequences = world(root, "BBC · ALBANESE", "Source: BBC News · 24 Sep 2026 · words attributed to Prime Minister Anthony Albanese");
    var response = el("div", "s81-response", consequences);
    el("div", "s81-response-mark", response, "“");
    var resptext = el("div", "s81-response-text", response);
    resptext.innerHTML = "He said it took <em>‘too long’</em> to inform officials. He said there would <em>‘obviously be legal consequences.’</em>";
    tl.fromTo(resptext, { y: 70, autoAlpha: 0 }, { y: 0, autoAlpha: 1, duration: .4, ease: "power2.out" }, 37.753);
    enter(tl, consequences, 37.753, 41.927, 0, 26, "power2.out");

    var privacy = world(root, "BBC · CURRENT QUALIFICATION", "Source: BBC News · 24 Sep 2026 · attributed to Anthony Albanese");
    var privacyLayout = el("div", "s81-privacy", privacy);
    var shield = el("div", "s81-shield", privacyLayout);
    el("div", "s81-shieldword", shield, "AT THIS\nSTAGE");
    var privacycopy = el("div", "s81-privacy-copy", privacyLayout);
    privacycopy.textContent = "No personal information is believed to have been accessed ‘at this stage’, but investigations are ongoing.";
    el("div", "s81-stage-label", privacycopy, "INVESTIGATION ONGOING");
    tl.fromTo(shield, { scale: .86, transformOrigin: "50% 50%" }, { scale: 1, duration: .38, ease: "power2.out" }, 41.827);
    tl.fromTo(privacycopy, { x: 65, autoAlpha: 0 }, { x: 0, autoAlpha: 1, duration: .25, ease: "power2.out" }, 41.65);
    tl.set(privacy, { autoAlpha: 0 }, 0);
    tl.fromTo(privacy, { autoAlpha: 0, y: 28 }, { autoAlpha: 1, y: 0, duration: .1, ease: "power2.out" }, 41.827);
    tl.to(privacy, { autoAlpha: 0, duration: .22, ease: "power1.in" }, 46.38);

    var lesson = world(root, "AGMM ILLUSTRATION · NOT A QUOTE", "AGMM lesson derived from the story · illustrative control route");
    var controls = el("div", "s81-controls", lesson);
    var control1 = el("div", "s81-control", controls);
    el("div", "s81-control-number", control1, "01 · ACCESS");
    el("div", "s81-control-icon", control1, "AI");
    el("div", "s81-control-label", control1, "Can an agent reach it?");
    el("div", "s81-link", controls);
    var control2 = el("div", "s81-control", controls);
    el("div", "s81-control-number", control2, "02 · ALERT");
    el("div", "s81-control-icon", control2, "24h");
    el("div", "s81-control-label", control2, "Who hears within the day?");
    var lessonEntryX = Math.min(24, 64 - 20);
    tl.fromTo(control1, { x: -lessonEntryX, autoAlpha: 1 }, { x: 0, autoAlpha: 1, duration: .4, ease: "power2.out", immediateRender: false }, 46.60);
    tl.fromTo(control2, { x: 80, autoAlpha: 0 }, { x: 0, autoAlpha: 1, duration: .4, ease: "power2.out" }, 46.88);
    tl.fromTo(controls.querySelector(".s81-link"), { scaleX: .05, transformOrigin: "0 50%" }, { scaleX: 1, duration: .36, ease: "power2.out" }, 47.16);
    enter(tl, lesson, 46.60, 51.60, 0, 28, "power2.out");

    var cta = world(root, "AGMM · FOLLOW FOR THE DAILY STORY", "AGMM · audit link shown in the final beat");
    cta.className += " s81-cta-world";
    el("div", "s81-cta-rule", cta);
    el("div", "s81-cta-title", cta, "ONE REAL AI\nSTORY A DAY");
    el("div", "s81-cta-url", cta, "agmm.co.uk/ai-constraint-audit");
    el("div", "s81-follow", cta, "FOLLOW · AGMM");
    var arrow = el("div", "s81-arrow", cta);
    tl.fromTo(cta.querySelector(".s81-cta-title"), { y: 60, autoAlpha: 0 }, { y: 0, autoAlpha: 1, duration: .23, ease: "back.out(1.05)" }, 51.56);
    tl.fromTo(cta.querySelector(".s81-cta-rule"), { scaleX: .04, transformOrigin: "0 50%" }, { scaleX: 1, duration: .45, ease: "power2.out" }, 51.82);
    tl.fromTo(cta.querySelector(".s81-cta-url"), { y: 38, autoAlpha: 0 }, { y: 0, autoAlpha: 1, duration: .35, ease: "power2.out" }, 52.02);
    tl.fromTo(arrow, { scaleX: .12, transformOrigin: "0 50%" }, { scaleX: 1, duration: .4, ease: "power2.out" }, 52.20);
    tl.set(cta, { autoAlpha: 0 }, 0);
    tl.fromTo(cta, { autoAlpha: 0 }, { autoAlpha: 1, duration: .18, ease: "power2.out" }, 51.56);
  };
})();
