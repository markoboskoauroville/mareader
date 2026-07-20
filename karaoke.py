# -*- coding: utf-8 -*-
"""
EdgeReader karaoke player.

Builds the self contained HTML/JS reader that Streamlit embeds. It receives, for
one text, every sentence's clip (audio as a data URI) plus per word timings, and
plays them one sentence at a time while sweeping the highlight word by word.

The smooth motion comes from the same drift corrected media clock MA Reader used:
mobile <audio> only reports currentTime a few times a second, so between native
ticks the clock free runs on wall time times the playback rate, and eases toward
each fresh currentTime. That keeps the red word glued to the voice.
"""
import json
import base64
import html as _html


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
    ttl = _html.escape(title or "")

    return TEMPLATE.replace("__DATA__", data)\
                   .replace("__SETTINGS__", st)\
                   .replace("__TITLE__", ttl)


TEMPLATE = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{
  --screen:#4696e6; --play:#37c878;
}
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
  display:flex; flex-direction:column; height:600px;
}
.rtitle{padding:12px 16px 0; color:var(--faint); font-size:12px;
  letter-spacing:.14em; text-transform:uppercase}
.doc{flex:1; overflow-y:auto; padding:14px 18px 22px; background:var(--page);
  color:var(--page-text); line-height:var(--lh,1.72);
  font-size:var(--fs,21px); font-family:var(--rf,Georgia,serif);
  -webkit-overflow-scrolling:touch}
.sent{border-radius:8px; padding:1px 2px; transition:background .12s,color .12s}
.sent.active{background:var(--sentbg); color:var(--sentfg)}
#wrap.focus .sent:not(.active){opacity:.32}
.sent .w{border-radius:4px; padding:0 1px}
.sent.active .w.cur{background:var(--wordbg); color:var(--wordfg);
  -webkit-box-decoration-break:clone; box-decoration-break:clone}
.controls{border-top:1px solid var(--line); background:var(--bg);
  padding:10px 14px 14px}
.bar{display:flex; align-items:center; justify-content:center; gap:22px}
.tb{border:none; background:transparent; color:var(--text); padding:0;
  display:flex; align-items:center; justify-content:center}
.tb svg{display:block}
.tb.skip{width:48px; height:48px; opacity:.85}
.tb.skip svg{width:28px; height:28px}
.tb.play{width:58px; height:58px}
.tb.play svg{width:40px; height:40px}
.tb.side{width:44px; height:44px; color:var(--dim); font-size:17px}
.tb.side.on{color:var(--text)}
.tb:active{opacity:.5}
.pos{display:flex; align-items:center; gap:10px; margin-top:8px;
  font-size:11px; color:var(--faint); font-variant-numeric:tabular-nums}
.pos input{flex:1; accent-color:var(--play)}
.count{margin-top:6px; text-align:center; font-size:11px; color:var(--faint)}
</style>
</head>
<body>
<div id="wrap">
  <div class="rtitle" id="rtitle">__TITLE__</div>
  <div class="doc" id="doc"></div>
  <div class="controls">
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
      <button class="tb side" id="focusB" title="Focus mode">&#9673;</button>
    </div>
    <div class="pos">
      <span id="cur">0:00</span>
      <input type="range" id="seek" min="0" max="1000" value="0">
      <span id="tot">0:00</span>
    </div>
    <div class="count" id="count"></div>
  </div>
</div>
<audio id="au" preload="auto"></audio>
<script>
"use strict";
const CLIPS = __DATA__;
const S = Object.assign({
  theme:"night", font:"serif", size:21, lineheight:3,
  sentRGB:[255,217,59], wordRGB:[226,59,78], fontRGB:[255,255,255],
  speed:1.0, gap:0.0, loop:false, autoplay:false, focus:false,
  wordhl:true, offsetMs:0, volume:100
}, __SETTINGS__);

const FONTS={
  serif:'Georgia,"Times New Roman",serif',
  sans :'system-ui,-apple-system,"Segoe UI",Roboto,sans-serif',
  book :'"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif',
  mono :'ui-monospace,"DejaVu Sans Mono",Menlo,Consolas,monospace',
  dyslexic:'system-ui,"Comic Sans MS",sans-serif'
};
const LH={1:1.35,2:1.5,3:1.72,4:1.95,5:2.2};
const WORD_LEAD=0.02;

const wrap=document.getElementById("wrap");
const doc=document.getElementById("doc");
const au=document.getElementById("au");
const playIcon=document.getElementById("playIcon");
const seek=document.getElementById("seek");
const curEl=document.getElementById("cur");
const totEl=document.getElementById("tot");
const countEl=document.getElementById("count");

let idx=0, playing=false, gapTimer=null;

/* ---- look ---- */
function rgb(a){return "rgb("+a[0]+","+a[1]+","+a[2]+")";}
function pickFg(a){const l=(a[0]*299+a[1]*587+a[2]*114)/1000; return l>140?"#12140a":"#ffffff";}
function applyLook(){
  wrap.dataset.theme=S.theme;
  wrap.classList.toggle("focus", !!S.focus);
  doc.style.setProperty("--rf", FONTS[S.font]||FONTS.serif);
  doc.style.setProperty("--fs", (S.size||21)+"px");
  doc.style.setProperty("--lh", LH[S.lineheight]||1.72);
  wrap.style.setProperty("--sentbg", rgb(S.sentRGB));
  wrap.style.setProperty("--sentfg", pickFg(S.sentRGB));
  wrap.style.setProperty("--wordbg", rgb(S.wordRGB));
  wrap.style.setProperty("--wordfg", rgb(S.fontRGB));
  document.getElementById("loopB").classList.toggle("on", !!S.loop);
  document.getElementById("focusB").classList.toggle("on", !!S.focus);
}

/* ---- render all sentences ---- */
function render(){
  doc.innerHTML="";
  CLIPS.forEach((c,i)=>{
    const p=document.createElement("span");
    p.className="sent"; p.dataset.i=i; p.innerHTML=c.html+" ";
    p.addEventListener("click",()=>{ load(i,true); });
    doc.appendChild(p);
  });
  countEl.textContent = CLIPS.length+" sentences";
}
function sentEl(i){ return doc.querySelector('.sent[data-i="'+i+'"]'); }

/* ---- drift corrected clock ---- */
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

/* ---- word highlight ---- */
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

/* ---- raf loop ---- */
let rafId=null;
function loop(){
  const clk=clockSample(au.currentTime, S.speed, playing && !au.paused);
  highlight(clk);
  const dur=CLIPS[idx].dur || au.duration || 1;
  const frac=Math.max(0,Math.min(1, clk/dur));
  seek.value=Math.round(frac*1000);
  curEl.textContent=fmt(clk);
  rafId=requestAnimationFrame(loop);
}
function startLoop(){ if(!rafId) rafId=requestAnimationFrame(loop); }
function stopLoop(){ if(rafId){cancelAnimationFrame(rafId); rafId=null;} }

function fmt(s){ s=Math.max(0,s|0); const m=(s/60)|0, r=s%60; return m+":"+(r<10?"0":"")+r; }

/* ---- load a sentence ---- */
function load(i, autoplay){
  if(i<0) i=0; if(i>=CLIPS.length) i=CLIPS.length-1;
  if(gapTimer){clearTimeout(gapTimer); gapTimer=null;}
  idx=i; curWord=-2; curSpans=null;
  doc.querySelectorAll(".sent").forEach(s=>s.classList.remove("active"));
  const el=sentEl(i);
  if(el){ el.classList.add("active");
          el.scrollIntoView({block:"center",behavior:"smooth"}); }
  au.src=CLIPS[i].audio;
  au.playbackRate=S.speed;
  au.volume=(S.volume==null?100:S.volume)/100;
  totEl.textContent=fmt(CLIPS[i].dur);
  clockReset(0);
  if(autoplay){ au.play().catch(()=>{}); }
}

/* ---- controls ---- */
function playPause(){
  if(au.paused){ au.play().catch(()=>{}); }
  else { au.pause(); }
}
function setPlayIcon(){
  playIcon.innerHTML = playing
    ? '<path d="M6 5h4v14H6zM14 5h4v14h-4z"/>'
    : '<path d="M8 5v14l11-7z"/>';
}
au.addEventListener("play",()=>{ playing=true; setPlayIcon(); clockReset(au.currentTime); startLoop(); });
au.addEventListener("pause",()=>{ playing=false; setPlayIcon(); });
au.addEventListener("ended",()=>{
  playing=false; setPlayIcon();
  const last = idx>=CLIPS.length-1;
  const advance=()=>{
    if(last){
      if(S.loop){ load(0,true); }
      else { clearWords(); }
    } else {
      load(idx+1,true);
    }
  };
  const g=(S.gap||0)*1000;
  if(g>0){ gapTimer=setTimeout(advance,g); } else { advance(); }
});

document.getElementById("playB").addEventListener("click",playPause);
document.getElementById("prevB").addEventListener("click",()=>load(idx-1,true));
document.getElementById("nextB").addEventListener("click",()=>load(idx+1,true));
document.getElementById("loopB").addEventListener("click",()=>{
  S.loop=!S.loop; document.getElementById("loopB").classList.toggle("on",S.loop);
});
document.getElementById("focusB").addEventListener("click",()=>{
  S.focus=!S.focus; wrap.classList.toggle("focus",S.focus);
  document.getElementById("focusB").classList.toggle("on",S.focus);
});
seek.addEventListener("input",()=>{
  const dur=CLIPS[idx].dur||au.duration||1;
  au.currentTime=(seek.value/1000)*dur; clockReset(au.currentTime);
});

/* ---- go ---- */
applyLook();
render();
load(0, !!S.autoplay);
setPlayIcon();
</script>
</body>
</html>
"""
