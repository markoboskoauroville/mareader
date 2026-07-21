# -*- coding: utf-8 -*-
"""
EdgeReader karaoke player.

A self contained HTML/JS reader that Streamlit embeds. It receives, for one text,
every sentence's clip (audio as a data URI) plus per word timings, and plays them
one sentence at a time while sweeping the highlight word by word.

Layout: the transport sits at the TOP so it stays in reach on long texts, and the
reading area fills the space below it and scrolls on its own. Smooth motion comes
from a drift corrected media clock: between the sparse native currentTime ticks it
free runs on wall time times the playback rate, then eases toward each fresh tick,
so the highlighted word stays glued to the voice.

The transport shows progress across the WHOLE text (all clips joined), elapsed and
total time, and a page counter (current sentence over total). Auto scroll can pin
the current sentence to the top of the reading area so the eye rests on one spot.
A fullscreen button opens an ebook mode where the controls vanish and only the
reading remains.
"""
import json
import base64
import html as _html

# Fonts offered in Settings, sans serif first (easier to read) then serifs, mono
# last. Web fonts load from Google Fonts inside the component so every choice
# renders the same on any machine, including Streamlit Cloud's Linux servers.
FONT_CHOICES = [
    ("sans",     "Sans (system)"),
    ("source",   "Source Sans"),
    ("nunito",   "Nunito (rounded)"),
    ("legible",  "Legible (Atkinson Hyperlegible)"),
    ("inter",    "Inter"),
    ("serif",    "Serif (Georgia)"),
    ("book",     "Book (Lora)"),
    ("garamond", "Garamond"),
    ("merri",    "Merriweather"),
    ("slab",     "Slab serif (Roboto Slab)"),
    ("mono",     "Monospace"),
]
FONT_KEYS = [k for k, _ in FONT_CHOICES]
DEFAULT_FONT = "sans"


def _sentence_html(text, words):
    """Wrap each visible word run in a span so JS can light it by index."""
    parts = []
    cur = 0
    for wi, w in enumerate(words):
        s, e = int(w["s"]), int(w["e"])
        if s < cur:
            s = cur
        if e < s:
            e = s
        if s > cur:
            parts.append(_html.escape(text[cur:s]))
        parts.append('<span class="w" data-w="%d">%s</span>'
                     % (wi, _html.escape(text[s:e])))
        cur = e
    if cur < len(text):
        parts.append(_html.escape(text[cur:]))
    return "".join(parts) or _html.escape(text)


def build_player(clips, settings, title=""):
    """clips: list of {text, words, mp3(bytes), dur}. settings: dict of look and
    playback options. Returns an HTML string for st.components.v1.html."""
    payload = []
    for c in clips:
        b64 = base64.b64encode(c["mp3"]).decode("ascii")
        payload.append({
            "html": _sentence_html(c["text"], c["words"]),
            "words": [{"t": float(w["t"]), "d": float(w["d"])} for w in c["words"]],
            "audio": "data:audio/mpeg;base64," + b64,
            "dur": float(c.get("dur", 0.0)),
        })
    data = json.dumps(payload)
    st = json.dumps(settings)
    return TEMPLATE.replace("__DATA__", data).replace("__SETTINGS__", st)


TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&family=EB+Garamond:wght@400;500&family=Inter:wght@400;600&family=Lora:wght@400;600&family=Merriweather:wght@400;700&family=Nunito:wght@400;700&family=Roboto+Slab:wght@400;600&family=Source+Sans+3:wght@400;600&display=swap');
:root{ --screen:#4696e6; --play:#37c878; }
*{box-sizing:border-box}
html,body{margin:0}
#wrap[data-theme="night"]{
  --bg:#080a10; --panel:#11141d; --line:#1d2230;
  --text:#cdd0d6; --dim:#7c8294; --faint:#565d6e;
  --page:#080a10; --page-text:#cdd0d6;
}
#wrap[data-theme="sepia"]{
  --bg:#efe3cc; --panel:#e6d9bd; --line:#d6c5a1;
  --text:#4a3f2e; --dim:#8a7a5c; --faint:#a99a78;
  --page:#f4ead4; --page-text:#43392a;
}
#wrap[data-theme="day"]{
  --bg:#f6f7fa; --panel:#ffffff; --line:#e1e4ea;
  --text:#1c2026; --dim:#5a616e; --faint:#9aa0ac;
  --page:#ffffff; --page-text:#1b1f25;
}
#wrap{
  background:var(--bg); color:var(--text);
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  border:1px solid var(--line); border-radius:14px; overflow:hidden;
  display:flex; flex-direction:column; height:600px; position:relative;
}
#wrap:fullscreen, #wrap:-webkit-full-screen{ height:100vh; border-radius:0; border:none; }

/* transport on top */
.controls{border-bottom:1px solid var(--line); background:var(--bg);
  padding:12px 14px 12px}
.bar{display:flex; align-items:center; justify-content:center; gap:20px}
.tb{border:none; background:transparent; color:var(--text); padding:0;
  display:flex; align-items:center; justify-content:center; cursor:pointer}
.tb svg{display:block}
.tb.skip{width:44px; height:44px; opacity:.85}
.tb.skip svg{width:26px; height:26px}
.tb.play{width:54px; height:54px}
.tb.play svg{width:38px; height:38px}
.tb.side{width:42px; height:42px; color:var(--dim); font-size:18px; line-height:1}
.tb.side.on{color:var(--text)}
.tb:active{opacity:.5}
.pos{display:flex; align-items:center; gap:12px; margin-top:9px;
  font-size:12px; color:var(--faint); font-variant-numeric:tabular-nums}
.pos input[type=range]{flex:1; accent-color:var(--play); height:4px}
.time{min-width:92px}
.page{min-width:56px; text-align:right; color:var(--dim); font-weight:600}

/* reading area below, scrolls on its own */
.doc{flex:1; overflow-y:auto; padding:20px 20px 26px; background:var(--page);
  color:var(--page-text); line-height:var(--lh,1.72);
  font-size:var(--fs,21px); font-family:var(--rf); scroll-behavior:smooth;
  -webkit-overflow-scrolling:touch}
.sent{border-radius:8px; padding:1px 2px; scroll-margin-top:16px;
  transition:background .12s,color .12s; cursor:pointer}
.sent.active{background:var(--sentbg); color:var(--sentfg)}
#wrap.focus .sent:not(.active){opacity:.30}
.sent .w{border-radius:4px; padding:0 1px}
.sent.active .w.cur{background:var(--wordbg); color:var(--wordfg);
  -webkit-box-decoration-break:clone; box-decoration-break:clone}

/* fullscreen ebook mode: controls gone, faint tap reveal */
#wrap.fullread .controls{ display:none; }
#wrap.fullread .doc{ padding:34px max(20px, 7vw) 44px; }
.fsui{position:absolute; z-index:10; opacity:0; transition:opacity .3s;
  pointer-events:none}
#wrap.fullread .fsui.show{opacity:1; pointer-events:auto}
.fsexit{top:14px; right:16px; width:42px; height:42px; border-radius:50%;
  border:none; background:rgba(128,128,128,.18); color:var(--text);
  font-size:20px; line-height:1; backdrop-filter:blur(4px); cursor:pointer}
.fsplay{left:50%; bottom:26px; transform:translateX(-50%); width:60px;
  height:60px; border-radius:50%; border:none; color:var(--text);
  background:rgba(128,128,128,.18); backdrop-filter:blur(4px); cursor:pointer;
  display:flex; align-items:center; justify-content:center}
.fsplay svg{width:34px; height:34px}
</style>
</head>
<body>
<div id="wrap">
  <div class="controls" id="controls">
    <div class="bar">
      <button class="tb side" id="loopB" title="Loop">&#8635;</button>
      <button class="tb skip" id="prevB" title="Previous sentence">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M6 6h2v12H6zM20 6v12L9 12z"/></svg>
      </button>
      <button class="tb play" id="playB" title="Play / pause">
        <svg id="playIcon" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
      </button>
      <button class="tb skip" id="nextB" title="Next sentence">
        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M16 6h2v12h-2zM4 6l11 6L4 18z"/></svg>
      </button>
      <button class="tb side" id="fsB" title="Fullscreen (ebook mode)">&#9974;</button>
    </div>
    <div class="pos">
      <span class="time" id="time">0:00 / 0:00</span>
      <input type="range" id="seek" min="0" max="1000" value="0">
      <span class="page" id="page">1 / 1</span>
    </div>
  </div>

  <div class="doc" id="doc"></div>

  <button class="fsui fsexit" id="fsExit" title="Exit fullscreen">&#10005;</button>
  <button class="fsui fsplay" id="fsPlay" title="Play / pause">
    <svg id="fsPlayIcon" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>
  </button>
</div>
<audio id="au" preload="auto"></audio>
<script>
"use strict";
const CLIPS = __DATA__;
const S = Object.assign({
  theme:"night", font:"sans", size:21, lineheight:3, scroll:"top",
  sentRGB:[255,217,59], wordRGB:[226,59,78], fontRGB:[255,255,255],
  speed:1.0, gap:0.0, loop:false, autoplay:false, focus:false,
  wordhl:true, offsetMs:0, volume:100
}, __SETTINGS__);

const FONTS={
  sans:'system-ui,-apple-system,"Segoe UI",Roboto,sans-serif',
  source:'"Source Sans 3",system-ui,sans-serif',
  nunito:'"Nunito",system-ui,sans-serif',
  legible:'"Atkinson Hyperlegible",system-ui,sans-serif',
  inter:'"Inter",system-ui,sans-serif',
  serif:'Georgia,"Times New Roman",serif',
  book:'"Lora",Georgia,serif',
  garamond:'"EB Garamond",Garamond,"Times New Roman",serif',
  merri:'"Merriweather",Georgia,serif',
  slab:'"Roboto Slab",Rockwell,Georgia,serif',
  mono:'ui-monospace,"DejaVu Sans Mono",Menlo,Consolas,monospace'
};
const LH={1:1.35,2:1.5,3:1.72,4:1.95,5:2.2};
const WORD_LEAD=0.02;

const STARTS=[]; let TOTAL=0;
CLIPS.forEach(c=>{ STARTS.push(TOTAL); TOTAL+=(c.dur||0); });
if(TOTAL<=0) TOTAL=1;

const wrap=document.getElementById("wrap");
const doc=document.getElementById("doc");
const au=document.getElementById("au");
const playIcon=document.getElementById("playIcon");
const fsPlayIcon=document.getElementById("fsPlayIcon");
const seek=document.getElementById("seek");
const timeEl=document.getElementById("time");
const pageEl=document.getElementById("page");

let idx=0, playing=false, gapTimer=null, seeking=false;
let pendingSeek=null, pendingPlay=false;

function rgb(a){return "rgb("+a[0]+","+a[1]+","+a[2]+")";}
function pickFg(a){const l=(a[0]*299+a[1]*587+a[2]*114)/1000; return l>140?"#12140a":"#ffffff";}
function applyLook(){
  wrap.dataset.theme=S.theme;
  wrap.classList.toggle("focus", !!S.focus);
  doc.style.setProperty("--rf", FONTS[S.font]||FONTS.sans);
  doc.style.setProperty("--fs", (S.size||21)+"px");
  doc.style.setProperty("--lh", LH[S.lineheight]||1.72);
  wrap.style.setProperty("--sentbg", rgb(S.sentRGB));
  wrap.style.setProperty("--sentfg", pickFg(S.sentRGB));
  wrap.style.setProperty("--wordbg", rgb(S.wordRGB));
  wrap.style.setProperty("--wordfg", rgb(S.fontRGB));
  document.getElementById("loopB").classList.toggle("on", !!S.loop);
}

function render(){
  doc.innerHTML="";
  CLIPS.forEach((c,i)=>{
    const p=document.createElement("span");
    p.className="sent"; p.dataset.i=i; p.innerHTML=c.html+" ";
    p.addEventListener("click",(e)=>{ e.stopPropagation(); load(i,true); });
    doc.appendChild(p);
  });
}
function sentEl(i){ return doc.querySelector('.sent[data-i="'+i+'"]'); }

const CLK={pred:0,lastWall:0,lastObs:-1,ready:false};
function clockReset(t){CLK.pred=t||0;CLK.lastWall=performance.now();CLK.lastObs=-1;CLK.ready=true;}
function clockSample(obs,rate,run){
  const now=performance.now();
  if(!CLK.ready){clockReset(obs);return CLK.pred;}
  const dt=(now-CLK.lastWall)/1000; CLK.lastWall=now;
  if(run) CLK.pred+=dt*(rate||1);
  if(obs!==CLK.lastObs){CLK.lastObs=obs;const err=obs-CLK.pred;
    if(Math.abs(err)>0.35)CLK.pred=obs; else CLK.pred+=err*0.5;}
  if(CLK.pred<0)CLK.pred=0;
  return CLK.pred;
}

let curWord=-2, curSpans=null;
function clearWords(){ if(curSpans){curSpans.forEach(s=>s.classList.remove("cur"));} }
function highlight(clk){
  if(!S.wordhl) return;
  const words=CLIPS[idx].words; if(!words||!words.length) return;
  const t=clk + WORD_LEAD + (S.offsetMs/1000);
  let hit=-1;
  for(let i=0;i<words.length;i++){
    if(t>=words[i].t && t<words[i].d){hit=i;break;}
    if(t>=words[i].t) hit=i;
  }
  if(hit===curWord) return;
  const el=sentEl(idx); if(!el) return;
  const spans=el.querySelectorAll(".w");
  if(curSpans) curSpans.forEach(s=>s.classList.remove("cur"));
  if(hit>=0 && spans[hit]) spans[hit].classList.add("cur");
  curSpans=spans; curWord=hit;
}

function fmt(s){ s=Math.max(0,s|0); const m=(s/60)|0, r=s%60; return m+":"+(r<10?"0":"")+r; }

let rafId=null;
function loop(){
  const clk=clockSample(au.currentTime, S.speed, playing && !au.paused);
  highlight(clk);
  const global = STARTS[idx] + Math.min(clk, CLIPS[idx].dur||clk);
  if(!seeking){
    seek.value=Math.round(Math.max(0,Math.min(1,global/TOTAL))*1000);
    timeEl.textContent = fmt(global)+" / "+fmt(TOTAL);
  }
  rafId=requestAnimationFrame(loop);
}
function startLoop(){ if(!rafId) rafId=requestAnimationFrame(loop); }

function setPage(){ pageEl.textContent=(idx+1)+" / "+CLIPS.length; }
function scrollTo(el){
  if(!el || S.scroll==="off") return;
  el.scrollIntoView({block:(S.scroll==="center"?"center":"start"), behavior:"smooth"});
}
function load(i, autoplay){
  if(i<0) i=0; if(i>=CLIPS.length) i=CLIPS.length-1;
  if(gapTimer){clearTimeout(gapTimer); gapTimer=null;}
  idx=i; curWord=-2; curSpans=null;
  doc.querySelectorAll(".sent").forEach(s=>s.classList.remove("active"));
  const el=sentEl(i);
  if(el){ el.classList.add("active"); scrollTo(el); }
  au.src=CLIPS[i].audio;
  au.playbackRate=S.speed;
  au.volume=(S.volume==null?100:S.volume)/100;
  clockReset(0);
  setPage();
  if(autoplay){ au.play().catch(()=>{}); }
}

function seekGlobal(globalTarget){
  globalTarget=Math.max(0,Math.min(TOTAL-0.01,globalTarget));
  let i=0;
  for(let k=0;k<CLIPS.length;k++){ if(globalTarget>=STARTS[k]) i=k; else break; }
  const offset=globalTarget-STARTS[i];
  const wasPlaying=playing;
  if(i===idx){ au.currentTime=offset; clockReset(offset); }
  else { pendingSeek=offset; pendingPlay=wasPlaying; load(i,false); }
}
au.addEventListener("loadedmetadata",()=>{
  if(pendingSeek!=null){
    try{ au.currentTime=pendingSeek; }catch(e){}
    clockReset(pendingSeek);
    if(pendingPlay) au.play().catch(()=>{});
    pendingSeek=null; pendingPlay=false;
  }
});

function playPause(){ if(au.paused){ au.play().catch(()=>{}); } else { au.pause(); } }
function setPlayIcon(){
  const p = playing ? '<path d="M6 5h4v14H6zM14 5h4v14h-4z"/>' : '<path d="M8 5v14l11-7z"/>';
  playIcon.innerHTML=p; fsPlayIcon.innerHTML=p;
}
au.addEventListener("play",()=>{ playing=true; setPlayIcon(); clockReset(au.currentTime); startLoop(); });
au.addEventListener("pause",()=>{ playing=false; setPlayIcon(); });
au.addEventListener("ended",()=>{
  playing=false; setPlayIcon();
  const last = idx>=CLIPS.length-1;
  const advance=()=>{ if(last){ if(S.loop){ load(0,true); } else { clearWords(); } } else { load(idx+1,true); } };
  const g=(S.gap||0)*1000;
  if(g>0){ gapTimer=setTimeout(advance,g); } else { advance(); }
});

document.getElementById("playB").addEventListener("click",playPause);
document.getElementById("prevB").addEventListener("click",()=>load(idx-1,true));
document.getElementById("nextB").addEventListener("click",()=>load(idx+1,true));
document.getElementById("loopB").addEventListener("click",()=>{
  S.loop=!S.loop; document.getElementById("loopB").classList.toggle("on",S.loop);
});
seek.addEventListener("input",()=>{ seeking=true;
  const g=(seek.value/1000)*TOTAL; timeEl.textContent=fmt(g)+" / "+fmt(TOTAL); });
seek.addEventListener("change",()=>{ seekGlobal((seek.value/1000)*TOTAL); seeking=false; });

function enterFS(){ const el=wrap;
  (el.requestFullscreen||el.webkitRequestFullscreen||el.msRequestFullscreen||function(){}).call(el); }
function exitFS(){
  (document.exitFullscreen||document.webkitExitFullscreen||document.msExitFullscreen||function(){}).call(document); }
function isFS(){ return document.fullscreenElement||document.webkitFullscreenElement; }
document.getElementById("fsB").addEventListener("click",()=>{ isFS()?exitFS():enterFS(); });
document.getElementById("fsExit").addEventListener("click",exitFS);
document.getElementById("fsPlay").addEventListener("click",(e)=>{ e.stopPropagation(); playPause(); nudge(); });
function onFSChange(){
  const on=!!isFS();
  wrap.classList.toggle("fullread",on);
  document.getElementById("fsB").classList.toggle("on",on);
  if(on) nudge(); else fsShow(false);
}
document.addEventListener("fullscreenchange",onFSChange);
document.addEventListener("webkitfullscreenchange",onFSChange);

let fadeTimer=null;
function fsShow(v){ document.querySelectorAll(".fsui").forEach(e=>e.classList.toggle("show",v)); }
function nudge(){ if(!isFS()) return; fsShow(true);
  if(fadeTimer) clearTimeout(fadeTimer); fadeTimer=setTimeout(()=>fsShow(false),2600); }
doc.addEventListener("mousemove",nudge);
doc.addEventListener("touchstart",nudge,{passive:true});
doc.addEventListener("click",()=>{ if(isFS()) nudge(); });

applyLook();
render();
load(0, !!S.autoplay);
setPlayIcon();
setPage();
</script>
</body>
</html>
"""
