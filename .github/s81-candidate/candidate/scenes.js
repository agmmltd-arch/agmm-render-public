/* S81 original evidence-route scene. Native AGK scene surface; no generic look pack or external media. */
(function () {
  var INK = "#13161b", PAPER = "#f1eee7", RED = "#bd292f", BLUE = "#3154a5", GREY = "#656c75", WHITE = "#fffdf8";
  var css = document.createElement("style");
  css.textContent = [
    ".s81-root{position:absolute;inset:0;overflow:hidden;background:" + PAPER + ";color:" + INK + ";font-family:'AG2 Instrument Sans',sans-serif}",
    ".s81-grain{position:absolute;inset:0;pointer-events:none;background-image:radial-gradient(rgba(19,22,27,.09) .7px,transparent .8px);background-size:11px 11px;opacity:.22}",
    ".s81-sheet{position:absolute;inset:80px 58px 90px;background:" + WHITE + ";border:2px solid #d9d5ce;box-shadow:0 26px 70px rgba(19,22,27,.17);padding:48px 46px;box-sizing:border-box;overflow:hidden}",
    ".s81-mast{font-family:'AG2 Red Hat Mono',monospace;font-size:42px;line-height:1.05;font-weight:700;letter-spacing:.02em;color:" + BLUE + ";border-bottom:3px solid " + INK + ";padding-bottom:20px}",
    ".s81-date{font:700 42px 'AG2 Red Hat Mono',monospace;color:" + RED + ";letter-spacing:.06em}",
    ".s81-hero{font:700 138px/.91 'AG2 Bricolage',sans-serif;letter-spacing:-.045em;text-transform:uppercase;margin-top:26px;white-space:pre-line}",
    ".s81-body{font:600 58px/1.08 'AG2 Instrument Sans',sans-serif;letter-spacing:-.025em;margin-top:30px;white-space:pre-line}",
    ".s81-credit{position:absolute;left:46px;right:46px;bottom:34px;border-top:2px solid #d8d4cc;padding-top:14px;font:700 34px/1.15 'AG2 Red Hat Mono',monospace;color:" + GREY + ";overflow-wrap:anywhere}",
    ".s81-tag{display:inline-block;font:700 34px 'AG2 Red Hat Mono',monospace;letter-spacing:.08em;text-transform:uppercase;border:3px solid " + RED + ";color:" + RED + ";padding:9px 13px;margin-top:22px}",
    ".s81-mark{position:absolute;right:42px;top:38px;width:148px;height:148px;object-fit:contain}",
    ".s81-route{position:absolute;left:74px;right:74px;top:990px;height:15px;background:#d4cfc6}",
    ".s81-route:before{content:'';position:absolute;inset:0 auto 0 0;width:var(--route,0%);background:" + RED + "}",
    ".s81-pin{position:absolute;top:958px;width:76px;height:76px;border:12px solid " + RED + ";border-radius:50%;background:" + PAPER + ";box-sizing:border-box}",
    ".s81-pin.jun{left:60px}.s81-pin.sep{right:60px}",
    ".s81-mail{position:absolute;right:78px;top:1070px;width:300px;height:208px;border:8px solid " + INK + ";background:#fff;box-shadow:0 18px 35px rgba(19,22,27,.14)}",
    ".s81-mail:after{content:'';position:absolute;left:24px;right:24px;top:18px;height:95px;border-bottom:7px solid " + INK + ";transform:skewY(-29deg)}",
    ".s81-month{position:absolute;left:62px;top:1040px;font:700 54px 'AG2 Red Hat Mono',monospace;color:" + RED + ";letter-spacing:.04em}",
    ".s81-question{position:absolute;left:54px;right:54px;top:290px;font:700 96px/.97 'AG2 Bricolage',sans-serif;letter-spacing:-.04em;text-transform:uppercase}",
    ".s81-rule{position:absolute;left:58px;right:58px;height:4px;background:" + RED + ";transform-origin:left center}",
    ".s81-qualification{font:600 42px/1.16 'AG2 Instrument Sans',sans-serif;color:" + GREY + ";margin-top:24px}",
    ".s81-signal{position:absolute;right:72px;top:1050px;width:230px;height:230px;border-radius:50%;border:8px solid " + RED + ";box-sizing:border-box}",
    ".s81-signal:after{content:'';position:absolute;inset:38px;border:7px solid " + RED + ";border-radius:50%}",
    ".s81-cta{font:700 122px/.95 'AG2 Bricolage',sans-serif;letter-spacing:-.04em;text-transform:uppercase}",
    ".s81-url{font:700 42px/1.25 'AG2 Red Hat Mono',monospace;color:" + BLUE + ";overflow-wrap:anywhere;margin-top:54px}",
    ".s81-illustration{position:absolute;right:50px;top:48px;font:700 28px 'AG2 Red Hat Mono',monospace;color:" + GREY + ";letter-spacing:.04em}",
    ".s81-fold{position:absolute;right:0;top:0;width:108px;height:108px;background:linear-gradient(225deg," + PAPER + " 49%,#d4cfc6 50%,#fff 53%)}"
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
  function at(tl, node, from, to) {
    if (from > 0) tl.set(node, { autoAlpha: 0 }, 0);
    tl.set(node, { autoAlpha: 1 }, from);
    tl.set(node, { autoAlpha: 0 }, to);
  }
  function push(tl, node, from, to) {
    tl.fromTo(node, { scale: 1, transformOrigin: "50% 42%" },
      { scale: 1.022, duration: Math.max(.2, to - from - .08), ease: "none" }, from);
  }
  function documentCard(root, title, body, credit, tag) {
    var d = el("article", "s81-sheet", root);
    el("div", "s81-mast", d, title);
    el("div", "s81-body", d, body);
    if (tag) el("div", "s81-tag", d, tag);
    el("div", "s81-credit", d, credit);
    el("i", "s81-fold", d);
    return d;
  }
  function logo(root) {
    var s = (window.S81_SRC || {}).items || {}, row = s.openaiMark || {};
    var im = el("img", "s81-mark", root);
    im.src = row.src || "media/openai-mark.svg";
    im.alt = "OpenAI mark, used to identify the company discussed";
    return im;
  }

  A.scenes["s81-evidence-route"] = function (ctx) {
    var S = AG.scene(ctx, "wall", 0, null, { drift: false });
    var root = el("div", "s81-root", S.cam);
    el("div", "s81-grain", root);
    var tl = ctx.tl;

    // Hook: identified company + month gap + the reported notification, moving from frame zero.
    var hook = el("section", "s81-sheet", root);
    logo(hook);
    el("div", "s81-mast", hook, "BBC NEWS  /  AUSTRALIA");
    el("div", "s81-date", hook, "JUNE  →  SEPTEMBER");
    el("div", "s81-hero", hook, "AGENT IN\nPORTAL");
    el("div", "s81-body", hook, "GENERAL INBOX\nTOLD IN SEPTEMBER");
    el("div", "s81-credit", hook, "BBC News · 24 Sep 2026 · source headline and report");
    var route = el("div", "s81-route", hook);
    var june = el("i", "s81-pin jun", hook), sept = el("i", "s81-pin sep", hook);
    var mail = el("i", "s81-mail", hook);
    var mark = { scale: 1.04, transformOrigin: "50% 50%" };
    tl.fromTo(hook, mark, { scale: 1, duration: .38, ease: "power2.out" }, 0);
    tl.fromTo(route, { "--route": "0%" }, { "--route": "100%", duration: 1.5, ease: "none" }, .08);
    push(tl, hook, 0, 8.60);
    tl.fromTo(june, { scale: .7 }, { scale: 1, duration: .18, ease: "power2.out" }, .12);
    tl.fromTo(sept, { scale: .7 }, { scale: 1, duration: .18, ease: "power2.out" }, 1.24);
    tl.fromTo(mail, { y: 90, rotation: 4 }, { y: 0, rotation: 0, duration: .24, ease: "power2.out" }, 6.22);

    // A sourced document is re-typeset as a quotation card; it is not represented as a screenshot.
    var breach = documentCard(root, "BBC · ALBANESE ON THE PORTAL", "The agent ‘infiltrated’ a statistics portal containing ‘non-sensitive’ Medicare data. He said it involved ‘public and non-public files.’", "Source: BBC News · report dated 24 Sep 2026 · bbc.com/news/articles/c6vgy0333dppo", "SOURCE QUOTATION");
    var statement = documentCard(root, "BBC · OPENAI STATEMENT", "“In the course of that, our models took actions we did not intend.”", "Source: OpenAI statement quoted by BBC News · 24 Sep 2026", "SOURCE QUOTATION");
    var context = documentCard(root, "BBC · OPENAI'S ACCOUNT", "OpenAI said its models were looking up statistics about Australia during an internal evaluation.", "Source: BBC News · report dated 24 Sep 2026 · bbc.com/news/articles/c6vgy0333dppo", "REPORTED ACCOUNT");
    var timeline = documentCard(root, "THE NOTIFICATION ROUTE", "JUNE\nPortal activity\n\nAUGUST\nOpenAI says it found out\n\n10 SEPTEMBER\nEmail to a government address", "Source: BBC News · dates and wording attributed in the report", "SOURCE TIMELINE");
    var guardian = documentCard(root, "THE GUARDIAN · THE INBOX", "The general Australian government email address “is monitored once a day.”", "Source: The Guardian · 24 Sep 2026 · theguardian.com/technology/2026/sep/24/openai-agent-hacked-medicare-australia-what-we-know-so-far-ntwnfb", "SOURCE QUOTATION");
    var consequences = documentCard(root, "BBC · ALBANESE", "He said it took “too long” to inform officials. He said there would “obviously be legal consequences.”", "Source: BBC News · 24 Sep 2026 · words attributed to Prime Minister Anthony Albanese", "SOURCE QUOTATION");
    var privacy = documentCard(root, "BBC · CURRENT QUALIFICATION", "No personal information is believed to have been accessed “at this stage”, but investigations are ongoing.", "Source: BBC News · 24 Sep 2026 · attributed to Anthony Albanese", "SOURCE QUALIFICATION");
    el("div", "s81-qualification", privacy, "The report does not say the investigation is complete.");

    var lesson = el("section", "s81-sheet", root);
    el("div", "s81-illustration", lesson, "AGMM ILLUSTRATION · NOT A QUOTE");
    el("div", "s81-question", lesson, "IF AN AGENT\nCAN TOUCH IT…\n\nWHO HEARS\nWITHIN THE DAY?");
    el("div", "s81-route", lesson);
    el("i", "s81-pin jun", lesson);
    var signal = el("i", "s81-signal", lesson);
    var rule = el("div", "s81-rule", lesson); rule.style.top = "980px";
    el("div", "s81-credit", lesson, "The question comes from S81's lesson; the diagram is illustrative.");
    tl.fromTo(signal, { scale: .72 }, { scale: 1, duration: .28, ease: "back.out(1.05)" }, 47.04);
    tl.fromTo(rule, { scaleX: .06 }, { scaleX: 1, duration: .48, ease: "power2.out" }, 47.18);

    var cta = el("section", "s81-sheet", root);
    el("div", "s81-cta", cta, "ONE REAL AI STORY A DAY");
    el("div", "s81-url", cta, "agmm.co.uk/ai-constraint-audit");
    el("div", "s81-credit", cta, "AGMM · audit link shown in the final beat");

    [breach, statement, context, timeline, guardian, consequences, privacy, lesson, cta].forEach(function (n) { n.style.visibility = "hidden"; });
    // Exact voice-anchored cuts from S81.words.json. A single opaque card is visible per range.
    at(tl, breach, 8.60, 18.40);
    // Keep the source card on the words being spoken: OpenAI's evaluation account first,
    // then the exact “actions we did not intend” quotation when that line begins.
    at(tl, context, 18.40, 24.667);
    at(tl, statement, 24.667, 29.20);
    at(tl, timeline, 29.20, 34.50);
    at(tl, guardian, 34.50, 37.753);
    at(tl, consequences, 37.753, 42.64);
    at(tl, privacy, 42.64, 46.60);
    at(tl, lesson, 46.60, 51.82);
    at(tl, cta, 51.82, 56.365);
    [[breach,8.60,18.40],[context,18.40,24.667],[statement,24.667,29.20],[timeline,29.20,34.50],
      [guardian,34.50,37.753],[consequences,37.753,42.64],[privacy,42.64,46.60],[lesson,46.60,51.82],[cta,51.82,56.365]].forEach(function (r) {
      push(tl, r[0], r[1], r[2]);
    });
  };
})();
