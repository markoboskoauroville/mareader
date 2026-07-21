# -*- coding: utf-8 -*-
"""
EdgeReader  v12 (a)

A Streamlit port of MA Reader Web. Paste any text, pick one of 26 Microsoft Edge
neural voices across 13 languages, and it speaks the text sentence by sentence
while highlighting each word in time with the voice. Word timing is measured from
the real audio waveform with ffmpeg.

The interface is deliberately minimal: three tabs, Reading, Transcribe &
Translate, and History. The Reading tab holds the text box; you paste in it and
press Read. The tab you last used, and all your settings, are remembered between
visits.

Look and playback settings are remembered between visits: they are saved in a
first party browser cookie and read back on the next session.
"""
import io
import json
import time
import base64
import hashlib
import zipfile

import streamlit as st

import engine
from karaoke import build_player, FONT_CHOICES, FONT_KEYS, DEFAULT_FONT

APP_NAME = "EdgeReader"
APP_VER = "v12 (a)"

VIEW_OPTS = ["Reading", "Transcribe & Translate", "History"]
READ_PH = "Paste or type text to read..."
TRANS_PH = "Transcript appears here, and is editable..."
TRANSL_PH = "Translation appears here, and is editable..."

st.set_page_config(page_title=APP_NAME, page_icon="\U0001F4D6",
                   layout="centered", initial_sidebar_state="collapsed")

# ---------- minimal dark chrome (no title, no menu clutter) ----------
st.markdown(
    """
    <style>
      .stApp { background:#080a10; color:#cdd0d6; }
      section[data-testid="stSidebar"] { background:#0b0e15; }
      [data-testid="stToolbar"] { display:none; }
      [data-testid="stDecoration"] { display:none; }
      footer { display:none; }
      .block-container { padding-top:2.4rem; padding-bottom:2rem; max-width:820px; }
      .ev { position:fixed; top:8px; right:14px; font-size:11px;
            color:#565d6e; letter-spacing:.06em; z-index:1000; }
      h1,h2,h3,h4 { color:#e6e8ee; }
      .stTextArea textarea { background:#11141d; color:#cdd0d6;
            border:1px solid #1d2230; font-size:15px; }
      div[data-baseweb="select"] > div { background:#11141d; border-color:#1d2230; }
      .stButton>button { background:#11141d; color:#cdd0d6; border:1px solid #1d2230; }
      .stButton>button:hover { border-color:#7d5cff; color:#fff; }
      .stDownloadButton>button { background:#11141d; color:#cdd0d6; border:1px solid #1d2230; }
      .muted { color:#7c8294; font-size:13px; }
    </style>
    <div class="ev">%s</div>
    """ % APP_VER,
    unsafe_allow_html=True,
)


# ---------- password gate ----------
# The password comes from secrets (app_password) and defaults to "kerstin" when
# not set. Leave it blank in secrets to turn protection off.
def _app_password():
    try:
        pw = st.secrets.get("app_password", "kerstin")
    except Exception:
        pw = "kerstin"
    return "" if pw is None else str(pw)


def _auth_token():
    return hashlib.sha256(("edgereader::" + _app_password()).encode("utf-8")).hexdigest()


def require_password():
    pw = _app_password()
    if not pw or st.session_state.get("_auth_ok"):
        return
    # auto login: a browser that already entered the right password carries a
    # matching token cookie, so it opens straight into the app
    try:
        tok = st.context.cookies.get("edgereader_auth")
    except Exception:
        tok = None
    if isinstance(tok, str) and tok == _auth_token():
        st.session_state["_auth_ok"] = True
        return
    st.markdown("<div style='max-width:340px;margin:14vh auto 0'>",
                unsafe_allow_html=True)
    st.markdown("#### \U0001F512 EdgeReader")
    st.caption("Password protected. Enter the password once and this device "
               "stays signed in.")
    entered = st.text_input("Password", type="password", key="_pw",
                            label_visibility="collapsed", placeholder="Password")
    st.button("Enter", type="primary", use_container_width=True)
    if entered:
        if entered == pw:
            st.session_state["_auth_ok"] = True
            st.rerun()
        else:
            st.error("Wrong password. Try again.")
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()


def persist_auth():
    """Once signed in, drop a token cookie so this browser auto logs in next
    time. Written once per session, on a normal render so it is not discarded."""
    if not st.session_state.get("_auth_ok") or st.session_state.get("_auth_written"):
        return
    if not _app_password():
        return
    st.session_state["_auth_written"] = True
    st.html('<script>document.cookie="edgereader_auth=%s; path=/; '
            'max-age=31536000; SameSite=Lax";</script>' % _auth_token(),
            unsafe_allow_javascript=True)


require_password()


# ---------- settings persistence (first party cookie) ----------
# Look and playback preferences are saved in a cookie so they survive a fresh
# session on stateless Streamlit Cloud. The Gemini key is deliberately NOT saved,
# since a cookie is readable on the device.
PERSIST_KEYS = ["enabled_langs", "voice_id", "theme", "font", "size",
                "lineheight", "scroll", "speed", "gap", "volume", "loop",
                "autoplay", "focus", "wordhl", "offset_ms",
                "sent_rgb", "word_rgb", "font_rgb", "viewsel",
                "tr_from", "tr_to", "tx_provider", "tl_provider", "tr_sex"]
COOKIE = "edgereader"
SPEEDS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5,
          1.75, 2.0, 2.25, 2.5]


def _encode_settings(d):
    raw = json.dumps(d, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_settings(blob):
    try:
        pad = blob + "=" * (-len(blob) % 4)
        return json.loads(base64.urlsafe_b64decode(pad.encode("ascii")).decode("utf-8"))
    except Exception:
        return {}


def _load_saved():
    try:
        raw = st.context.cookies.get(COOKIE)
    except Exception:
        raw = None
    if not isinstance(raw, str):
        return {}
    return _decode_settings(raw) if raw else {}


def persist_settings():
    """Write current preferences to the cookie, but only when they change, so
    the invisible writer element is emitted just on the run that changed."""
    payload = {k: st.session_state.get(k) for k in PERSIST_KEYS}
    blob = _encode_settings(payload)
    if st.session_state.get("_saved_sig") == blob:
        return
    st.session_state["_saved_sig"] = blob
    st.html('<script>document.cookie="%s=%s; path=/; max-age=31536000; '
            'SameSite=Lax";</script>' % (COOKIE, blob),
            unsafe_allow_javascript=True)


# ---------- archive persistence (chunked cookies, holds full texts) ----------
# The archive can carry long texts, too big for one cookie, so it is base64'd and
# split across numbered cookies (edgereader_a0, a1, ...) with a count in
# edgereader_ac. Oldest pieces are dropped from persistence only if the whole set
# would exceed the cap; they stay in the session either way.
ARCH_PREFIX = "edgereader_a"
ARCH_COUNT = "edgereader_ac"
ARCH_CHUNK = 3000          # base64 chars per cookie
ARCH_MAX_CHUNKS = 10       # ~30 KB of base64, ~22 KB of text


def _archive_blob(archive):
    slim = [{"i": m["id"], "t": m["title"], "x": m["text"]} for m in archive]
    raw = json.dumps(slim, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _archive_from_blob(blob):
    try:
        pad = blob + "=" * (-len(blob) % 4)
        slim = json.loads(base64.urlsafe_b64decode(pad.encode("ascii")).decode("utf-8"))
        out = []
        for m in slim:
            t = m.get("x", "")
            out.append({"id": m.get("i", int(time.time() * 1000)),
                        "title": m.get("t", "Untitled"), "text": t,
                        "chars": len(t)})
        return out
    except Exception:
        return []


def _saved_chunk_count():
    try:
        v = st.context.cookies.get(ARCH_COUNT, "0")
    except Exception:
        return 0
    return int(v) if isinstance(v, str) and v.isdigit() else 0


def _load_archive():
    n = _saved_chunk_count()
    if n <= 0:
        return []
    parts = []
    for i in range(min(n, ARCH_MAX_CHUNKS)):
        try:
            v = st.context.cookies.get(ARCH_PREFIX + str(i), "")
        except Exception:
            v = ""
        parts.append(v if isinstance(v, str) else "")
    return _archive_from_blob("".join(parts))


def persist_archive():
    """Mirror the session archive into chunked cookies, trimming the oldest
    pieces only if the set would overflow the cap. Writes only on change."""
    arch = list(st.session_state.archive)
    cap = ARCH_CHUNK * ARCH_MAX_CHUNKS
    while arch and len(_archive_blob(arch)) > cap:
        arch = arch[:-1]                       # archive is newest first
    blob = _archive_blob(arch)
    if st.session_state.get("_arch_sig") == blob:
        return
    st.session_state["_arch_sig"] = blob
    chunks = [blob[i:i + ARCH_CHUNK] for i in range(0, len(blob), ARCH_CHUNK)] or [""]
    n = len(chunks)
    prev = st.session_state.get("_arch_prevn", 0)
    js = []
    for i, ch in enumerate(chunks):
        js.append('document.cookie="%s%d=%s; path=/; max-age=31536000; SameSite=Lax";'
                   % (ARCH_PREFIX, i, ch))
    for i in range(n, prev):                   # clear stale chunks after shrink
        js.append('document.cookie="%s%d=; path=/; max-age=0";' % (ARCH_PREFIX, i))
    js.append('document.cookie="%s=%d; path=/; max-age=31536000; SameSite=Lax";'
              % (ARCH_COUNT, n))
    st.session_state["_arch_prevn"] = n
    st.html("<script>" + "".join(js) + "</script>", unsafe_allow_javascript=True)


# ---------- session defaults (seeded from the saved cookie) ----------
def _init():
    s = st.session_state
    saved = _load_saved()

    def d(key, default):        # persisted: prefer the saved value
        s.setdefault(key, saved.get(key, default))

    # non persisted, always fresh
    s.setdefault("pastebox", "")
    s.setdefault("gemini_key", "")
    s.setdefault("clips", None)
    s.setdefault("clips_voice", None)
    s.setdefault("clips_title", "")
    s.setdefault("archive", _load_archive())
    s.setdefault("_arch_prevn", _saved_chunk_count())
    s.setdefault("offline_sig", "")
    # translate tab
    d("tr_from", "auto")
    d("tr_to", "de")
    d("tx_provider", "groq")     # groq (whisper) or assemblyai
    d("tl_provider", "groq")     # groq or google
    d("tr_sex", "F")
    s.setdefault("tr_src", "")
    s.setdefault("tr_out", "")
    s.setdefault("tr_clips", None)
    s.setdefault("tr_sig", "")

    # persisted look and playback
    d("enabled_langs", list(engine.DEFAULT_LANGS))
    d("voice_id", 1)
    d("theme", "night")
    d("font", DEFAULT_FONT)
    d("size", 21)
    d("lineheight", 3)
    d("scroll", "top")
    d("speed", 1.0)
    d("gap", 0.0)
    d("volume", 100)
    d("loop", False)
    d("autoplay", True)
    d("focus", False)
    d("wordhl", True)
    d("offset_ms", 0)
    d("sent_rgb", [255, 217, 59])
    d("word_rgb", [226, 59, 78])
    d("font_rgb", [255, 255, 255])
    d("viewsel", "Reading")
    if s.get("viewsel") not in VIEW_OPTS:
        s["viewsel"] = "Reading"

    # validate anything a stale or hand edited cookie could get wrong
    if s.theme not in ("night", "sepia", "day"):
        s.theme = "night"
    if s.font not in FONT_KEYS:
        s.font = DEFAULT_FONT
    if s.scroll not in ("top", "center", "off"):
        s.scroll = "top"
    if s.speed not in SPEEDS:
        s.speed = 1.0
    if not isinstance(s.enabled_langs, list) or not s.enabled_langs:
        s.enabled_langs = list(engine.DEFAULT_LANGS)
    else:
        valid = {lg["key"] for lg in engine.LANGS}
        s.enabled_langs = [k for k in s.enabled_langs if k in valid] \
            or list(engine.DEFAULT_LANGS)
    for k in ("sent_rgb", "word_rgb", "font_rgb"):
        v = s.get(k)
        if not (isinstance(v, list) and len(v) == 3
                and all(isinstance(x, int) and 0 <= x <= 255 for x in v)):
            s[k] = {"sent_rgb": [255, 217, 59], "word_rgb": [226, 59, 78],
                    "font_rgb": [255, 255, 255]}[k]


_init()
S = st.session_state


# ---------- cached synthesis ----------
@st.cache_data(show_spinner=False, max_entries=64)
def _synth_cached(text, voice_edge):
    return engine.synth_sentences(text, voice_edge)


def voice_edge_of(vid):
    v = engine.VOICES.get(vid)
    return v[0] if v else engine.VOICES[1][0]


def voice_name_of(vid):
    v = engine.VOICES.get(vid)
    return v[1] if v else ""


def voice_vkey_of(vid):
    v = engine.VOICES.get(vid)
    return v[4] if v else "sansF"


def enabled_voice_options():
    ids, labels = [], []
    for v in engine.voices_list():
        if v["lang"] in S.enabled_langs:
            ids.append(v["id"])
            labels.append("%s  \u00b7  %s" % (v["name"], v["label"]))
    if not ids:
        for v in engine.voices_list():
            ids.append(v["id"])
            labels.append("%s  \u00b7  %s" % (v["name"], v["label"]))
    return labels, ids


def current_settings():
    return {
        "theme": S.theme, "font": S.font, "size": S.size,
        "lineheight": S.lineheight, "scroll": S.scroll, "speed": S.speed,
        "gap": S.gap, "volume": S.volume, "loop": S.loop, "autoplay": S.autoplay,
        "focus": S.focus, "wordhl": S.wordhl, "offsetMs": S.offset_ms,
        "sentRGB": S.sent_rgb, "wordRGB": S.word_rgb, "fontRGB": S.font_rgb,
    }


def title_from(text):
    return next((ln.strip()[:60] for ln in text.splitlines() if ln.strip()),
                "Untitled")


def secret_keys(*array_names, numbered=None):
    """Read API keys from Streamlit secrets. Accepts a TOML array under any of
    array_names (or a single string), and optionally numbered singles like
    <numbered>_1, <numbered>_2 ... stopping at the first gap. Deduped, ordered."""
    keys = []
    for name in array_names:
        try:
            v = st.secrets.get(name)
        except Exception:
            v = None
        if isinstance(v, str) and v.strip():
            keys.append(v.strip())
        elif isinstance(v, (list, tuple)):
            keys += [k.strip() for k in v if isinstance(k, str) and k.strip()]
    if numbered:
        i = 1
        while i <= 50:
            try:
                kv = st.secrets.get("%s_%d" % (numbered, i))
            except Exception:
                kv = None
            if isinstance(kv, str) and kv.strip():
                keys.append(kv.strip())
                i += 1
            else:
                break
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def groq_keys():
    return secret_keys("groq_keys", numbered="groq_key")


def aai_keys():
    return secret_keys("assemblyai_keys", numbered="assemblyai_key")


def google_keys():
    return secret_keys("google_keys", "gemini_keys", numbered="google_key")


def has_groq():
    return len(groq_keys()) > 0


def ai_title(text):
    """A Groq generated title for the whole text, rotating the keys. Falls back
    to the first line if Groq is unavailable."""
    keys = groq_keys()
    if keys:
        st.session_state["groq_rr"] = st.session_state.get("groq_rr", 0) + 1
        title, _ = engine.groq_title(text, keys, start=st.session_state["groq_rr"])
        if title:
            return title
    return title_from(text)


def archive_json():
    return json.dumps(
        {"app": "EdgeReader", "schema": "archive/1", "exported": int(time.time()),
         "pieces": [{"id": m["id"], "title": m["title"], "text": m["text"]}
                    for m in st.session_state.archive]},
        ensure_ascii=False, indent=1)


def import_archive_json(raw):
    """Merge pieces from an exported archive json, skipping duplicates. Returns
    the number added."""
    data = json.loads(raw)
    pieces = data.get("pieces", data) if isinstance(data, dict) else data
    if not isinstance(pieces, list):
        return 0
    have_ids = {m["id"] for m in st.session_state.archive}
    have_txt = {m["text"] for m in st.session_state.archive}
    added = 0
    for p in pieces:
        if not isinstance(p, dict):
            continue
        t = (p.get("text") or "").strip()
        if not t or p.get("id") in have_ids or t in have_txt:
            continue
        pid = p.get("id") or (int(time.time() * 1000) + added)
        st.session_state.archive.append(
            {"id": pid, "title": p.get("title") or title_from(t),
             "text": t, "chars": len(t)})
        have_ids.add(pid)
        have_txt.add(t)
        added += 1
    st.session_state.archive.sort(key=lambda m: m["id"], reverse=True)
    return added


def remember_text(text):
    """File a pasted text into history, newest first, or move it to the top if
    it is already there so it is never duplicated. Returns its title."""
    t = text.strip()
    if not t:
        return "Untitled"
    for m in S.archive:
        if m["text"].strip() == t:
            S.archive.remove(m)
            S.archive.insert(0, m)
            return m["title"]
    title = ai_title(text)
    S.archive.insert(0, {"id": int(time.time() * 1000), "title": title,
                         "text": text, "chars": len(text)})
    return title


def synth_voice(text, voice_edge):
    """Synthesise text with a specific voice (used to speak translations in the
    target language). Returns (clips, error)."""
    clean = engine.clean_text(text)
    if not clean.strip():
        return None, "Nothing to speak."
    return _synth_cached(clean, voice_edge)


def read_text(text, remember=False):
    """Synthesise `text` in the current voice and, on success, switch to the
    Reading tab. When remember is set, the text is also filed into history.
    Returns an error string, or '' on success."""
    clean = engine.clean_text(text)
    if not clean.strip():
        return "Paste some text first."
    with st.spinner("Generating the voice, sentence by sentence, and measuring "
                    "word timing from the audio..."):
        clips, err = _synth_cached(clean, voice_edge_of(S.voice_id))
    if err or not clips:
        return err or "Nothing was produced."
    if remember:
        with st.spinner("Titling..." if has_groq() else ""):
            title = remember_text(text)
    else:
        title = title_from(text)
    S.clips = clips
    S.clips_voice = S.voice_id
    S.clips_title = title
    st.session_state["_pending_view"] = "Reading"
    return ""


def copy_paste_bar(placeholder, uid):
    """Render Copy and Paste buttons above a text box. They act on the browser
    clipboard client side, targeting the textarea by its placeholder."""
    ph = json.dumps(placeholder)
    st.html(
        '<div style="display:flex;gap:6px;margin:2px 0 2px">'
        '<button id="cp_%s" type="button" style="background:#11141d;color:#cdd0d6;'
        'border:1px solid #1d2230;border-radius:8px;padding:3px 12px;font-size:12px;'
        'cursor:pointer">Copy</button>'
        '<button id="ps_%s" type="button" style="background:#11141d;color:#cdd0d6;'
        'border:1px solid #1d2230;border-radius:8px;padding:3px 12px;font-size:12px;'
        'cursor:pointer">Paste</button></div>'
        '<script>(function(){var ph=%s;'
        'function doc(){try{if(window.parent&&window.parent.document)return window.parent.document;}catch(e){}return document;}'
        'function ta(){return doc().querySelector("textarea[placeholder="+JSON.stringify(ph)+"]");}'
        'var c=document.getElementById("cp_%s"),p=document.getElementById("ps_%s");'
        'if(c)c.addEventListener("click",function(){var t=ta();if(t&&navigator.clipboard)navigator.clipboard.writeText(t.value||"");});'
        'if(p)p.addEventListener("click",function(){var t=ta();if(!t||!navigator.clipboard||!navigator.clipboard.readText)return;'
        'navigator.clipboard.readText().then(function(v){var s=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,"value").set;'
        's.call(t,v);t.dispatchEvent(new Event("input",{bubbles:true}));t.dispatchEvent(new Event("change",{bubbles:true}));t.focus();});});'
        '})();</script>' % (uid, uid, ph, uid, uid),
        unsafe_allow_javascript=True)


def build_export_zip(clips, title, vid):
    buf = io.BytesIO()
    sents, duration = [], 0.0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for c in clips:
            clip = "s%04d.mp3" % c["i"]
            z.writestr("clips/" + clip, c["mp3"])
            sents.append({"i": c["i"], "text": c["text"], "clip": clip,
                          "dur": c["dur"], "words": c["words"]})
            duration += c["dur"]
        z.writestr("text.txt", "\n".join(c["text"] for c in clips) + "\n")
        z.writestr("manifest.json", json.dumps({
            "app": "EdgeReader", "schema": "edgereader/1",
            "title": title or "Untitled", "voice": voice_name_of(vid),
            "vkey": voice_vkey_of(vid),
            "lang": engine.VOICES[vid][2] if vid in engine.VOICES else "",
            "created": int(time.time()), "duration": round(duration, 3),
            "sentences": sents}, ensure_ascii=False, indent=1))
    buf.seek(0)
    return buf.getvalue()


def clips_from_zip(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        clips = []
        for sen in manifest.get("sentences", []):
            clips.append({"i": sen.get("i", 0), "text": sen.get("text", ""),
                          "mp3": z.read("clips/" + sen.get("clip", "")),
                          "words": sen.get("words", []),
                          "dur": sen.get("dur", 0.0)})
    return manifest, clips


def _clear_paste():
    st.session_state.pastebox = ""


def _reset_all():
    """Start again: clear every text box and the current audio, keep History,
    settings, and sign in."""
    for k in ("pastebox", "tr_src", "tr_out"):
        st.session_state[k] = ""
    st.session_state["clips"] = None
    st.session_state["clips_title"] = ""
    st.session_state["tr_clips"] = None
    st.session_state["offline_sig"] = ""
    st.session_state["tr_sig"] = ""


# =========================================================================
# Sidebar: voice, look, playback, colours, languages, then tools
# =========================================================================
with st.sidebar:
    st.markdown("###### Voice")
    labels, ids = enabled_voice_options()
    if S.voice_id not in ids:
        S.voice_id = ids[0]
    sel = st.selectbox("Reading voice", labels, index=ids.index(S.voice_id),
                       label_visibility="collapsed")
    S.voice_id = ids[labels.index(sel)]

    with st.expander("Reading look", expanded=True):
        S.theme = st.radio("Theme", ["night", "sepia", "day"],
                           index=["night", "sepia", "day"].index(S.theme),
                           horizontal=True)
        if S.font not in FONT_KEYS:
            S.font = DEFAULT_FONT
        flabels = [lbl for _, lbl in FONT_CHOICES]
        fsel = st.selectbox("Font", flabels, index=FONT_KEYS.index(S.font))
        S.font = FONT_KEYS[flabels.index(fsel)]
        S.size = st.slider("Text size", 14, 40, S.size)
        S.lineheight = st.slider("Line spacing", 1, 5, S.lineheight)
        scroll_opts = {"top": "Auto-scroll: keep sentence at top",
                       "center": "Auto-scroll: keep sentence centered",
                       "off": "Auto-scroll: off"}
        skeys = list(scroll_opts.keys())
        ssel = st.selectbox("Auto-scroll", [scroll_opts[k] for k in skeys],
                            index=skeys.index(S.scroll))
        S.scroll = skeys[[scroll_opts[k] for k in skeys].index(ssel)]
        S.focus = st.checkbox("Focus mode (dim other sentences)", S.focus)

    with st.expander("Playback", expanded=False):
        S.speed = st.select_slider("Speed", SPEEDS, value=S.speed)
        S.gap = st.slider("Gap between sentences (s)", 0.0, 3.0, S.gap, 0.1)
        S.volume = st.slider("Volume", 0, 100, S.volume, 5)
        S.loop = st.checkbox("Loop", S.loop)
        S.autoplay = st.checkbox("Auto-play on open", S.autoplay)

    with st.expander("Highlight colours (R G B)", expanded=False):
        S.wordhl = st.checkbox("Highlight the word being read", S.wordhl)

        def rgb_row(label, key):
            st.caption(label)
            c = st.columns([1, 1, 1, 1])
            v = S[key]
            r = c[0].number_input("R", 0, 255, v[0], key=key + "_r",
                                  label_visibility="collapsed")
            g = c[1].number_input("G", 0, 255, v[1], key=key + "_g",
                                  label_visibility="collapsed")
            b = c[2].number_input("B", 0, 255, v[2], key=key + "_b",
                                  label_visibility="collapsed")
            c[3].markdown("<div style='height:34px;border-radius:6px;border:1px "
                          "solid #1d2230;background:rgb(%d,%d,%d)'></div>"
                          % (r, g, b), unsafe_allow_html=True)
            S[key] = [int(r), int(g), int(b)]

        rgb_row("Sentence highlight background", "sent_rgb")
        rgb_row("Word highlight background", "word_rgb")
        rgb_row("Highlighted word text colour", "font_rgb")

        sb, wb, wf = S.sent_rgb, S.word_rgb, S.font_rgb
        sfg = "#12140a" if (sb[0]*299 + sb[1]*587 + sb[2]*114)/1000 > 140 else "#ffffff"
        st.markdown(
            "<div style='margin-top:8px;font-size:15px'>Sample: "
            "<span style='background:rgb(%d,%d,%d);color:%s;padding:2px 6px;border-radius:6px'>"
            "the <span style='background:rgb(%d,%d,%d);color:rgb(%d,%d,%d);padding:1px 4px;border-radius:4px'>word</span>"
            " being read</span></div>"
            % (sb[0], sb[1], sb[2], sfg, wb[0], wb[1], wb[2], wf[0], wf[1], wf[2]),
            unsafe_allow_html=True)
        S.offset_ms = st.slider("Timing nudge (ms) \u00b7 later \u2192 earlier",
                                -300, 300, S.offset_ms, 20)

    with st.expander("Languages", expanded=False):
        st.caption("Tick a language to add its two voices to the picker.")
        cat = engine.langs_catalogue()
        cols = st.columns(2)
        chosen = []
        for n, lg in enumerate(cat):
            with cols[n % 2]:
                lbl = lg["label"] + (("  (%s)" % lg["native"]) if lg["native"] else "")
                if st.checkbox(lbl, value=(lg["key"] in S.enabled_langs),
                               key="lang_%s" % lg["key"]):
                    chosen.append(lg["key"])
                if lg.get("uses"):
                    st.caption("Also: " + lg["uses"])
        S.enabled_langs = chosen

    st.markdown("---")

    if S.clips:
        st.download_button(
            "Export current reading (.zip)",
            data=build_export_zip(S.clips, S.clips_title, S.clips_voice or S.voice_id),
            file_name="%s.zip" % (S.clips_title or "edgereader"),
            mime="application/zip", use_container_width=True)

    with st.expander("Offline file", expanded=False):
        st.caption("Play back an EdgeReader export .zip without re-generating.")
        up = st.file_uploader("Export .zip", type=["zip"],
                              label_visibility="collapsed")
        if up is not None:
            sig = "%s:%d" % (up.name, up.size)
            if sig != S.offline_sig:
                try:
                    manifest, clips = clips_from_zip(up.read())
                    S.clips = clips
                    S.clips_voice = S.voice_id
                    S.clips_title = manifest.get("title", "Offline")
                    S.offline_sig = sig
                    st.session_state["_pending_view"] = "Reading"
                    st.rerun()
                except Exception as e:
                    st.error("Not an EdgeReader export: %s" % e)

    with st.expander("Keys and AI (secrets)", expanded=False):
        ng, na, nk = len(groq_keys()), len(aai_keys()), len(google_keys())
        st.caption("Loaded from secrets: Groq %d, AssemblyAI %d, Google %d."
                   % (ng, na, nk))
        st.caption("Groq is free and powers titles, translation, and Whisper "
                   "transcription. AssemblyAI and Google are paid alternatives. "
                   "Put as many keys as you like per provider; they are tried in "
                   "order, so if one is rate limited the next is used.")
        st.caption("On Streamlit Cloud: App, Settings, Secrets. Format:")
        st.code(
            'groq_keys = [\n  "gsk_key_1",\n  "gsk_key_2",\n]\n\n'
            'assemblyai_keys = [\n  "aai_key_1",\n  "aai_key_2",\n]\n\n'
            'google_keys = [\n  "AQ.Ab_key_1",\n  "AQ.Ab_key_2",\n]\n\n'
            '# numbered singles also work:\n'
            '# assemblyai_key_1 = "aai_key_1"\n'
            '# assemblyai_key_2 = "aai_key_2"',
            language="toml")

    with st.expander("Help", expanded=False):
        st.markdown(
            "Paste or type text in the **Reading** tab and press **Read**. The "
            "app speaks "
            "it with the words lighting up in time, and files the text in "
            "**History** automatically. History keeps only the text, never the "
            "audio, so any piece can be spoken again with its Read with TTS "
            "button. History is saved in your browser and kept between visits, "
            "and can be downloaded or imported as a file. With Groq keys in "
            "secrets, each piece is titled automatically. The Reading tab shows "
            "the player, with a fullscreen ebook mode.")


# =========================================================================
# Main area: three tabs, Reading, Transcribe & Translate, History
# =========================================================================
if "_pending_view" in st.session_state:
    st.session_state["viewsel"] = st.session_state.pop("_pending_view")

_, xc = st.columns([5, 1])
xc.button("\u2715", help="Clear the text boxes and current audio, start again",
          on_click=_reset_all, use_container_width=True)

hist_label = "History (%d)" % len(S.archive) if S.archive else "History"
_tab_label = {"Reading": "Reading",
              "Transcribe & Translate": "Transcribe & Translate",
              "History": hist_label}
st.segmented_control("mode", VIEW_OPTS, key="viewsel", required=True,
                     width="stretch", label_visibility="collapsed",
                     format_func=lambda v: _tab_label.get(v, v))
view = st.session_state.get("viewsel") or "Reading"

st.write("")

if view == "Reading":
    copy_paste_bar(READ_PH, "rd")
    st.text_area("Reading text", key="pastebox", height=200,
                 label_visibility="collapsed", placeholder=READ_PH)
    a, b = st.columns([2, 1])
    if a.button("Read", type="primary", use_container_width=True):
        err = read_text(S.pastebox, remember=True)
        if err:
            st.warning(err)
        else:
            st.rerun()
    b.button("Clear", use_container_width=True, on_click=_clear_paste)

    if S.clips:
        eng = S.clips[0].get("engine", "edge")
        src = "waveform" if eng == "pcm" else "voice marks"
        st.markdown("<span class='muted'>%d sentences \u00b7 %s \u00b7 timing: %s"
                    "</span>" % (len(S.clips), voice_name_of(S.clips_voice or S.voice_id), src),
                    unsafe_allow_html=True)
        st.iframe(build_player(S.clips, current_settings()), height=620)

elif view == "History":
    st.markdown("<span class='muted'>Everything you read is kept here as text "
                "and saved between visits. Press Read with TTS to hear any piece "
                "again.</span>", unsafe_allow_html=True)

    tools = st.columns([1, 1, 1])
    if S.archive:
        tools[0].download_button("Download all (.json)", data=archive_json(),
                                 file_name="edgereader-history.json",
                                 mime="application/json", use_container_width=True)
        if tools[2].button("Delete all", use_container_width=True):
            S.archive = []
            st.rerun()
    imp = tools[1].file_uploader("Import (.json)", type=["json"],
                                 label_visibility="collapsed")
    if imp is not None:
        isig = "%s:%d" % (imp.name, imp.size)
        if isig != S.get("imp_sig", ""):
            S["imp_sig"] = isig
            try:
                n = import_archive_json(imp.read().decode("utf-8"))
                st.success("Imported %d piece%s." % (n, "" if n == 1 else "s"))
                if n:
                    st.rerun()
            except Exception as e:
                st.error("Could not read that file: %s" % e)

    if not S.archive:
        st.markdown("<span class='muted'>No history yet.</span>",
                    unsafe_allow_html=True)
    for m in list(S.archive):
        with st.container(border=True):
            st.markdown("**%s**  \n<span class='muted'>%d chars</span>"
                        % (m["title"], m["chars"]), unsafe_allow_html=True)
            a, b, c = st.columns([2, 1, 1])
            if a.button("Read with TTS", key="rd_%s" % m["id"],
                        type="primary", use_container_width=True):
                err = read_text(m["text"], remember=False)
                if err:
                    st.error(err)
                else:
                    st.rerun()
            if b.button("Title", key="ti_%s" % m["id"], use_container_width=True,
                        disabled=not has_groq(), help="Retitle with Groq"):
                with st.spinner("Titling..."):
                    S["groq_rr"] = S.get("groq_rr", 0) + 1
                    t, gerr = engine.groq_title(m["text"], groq_keys(),
                                                start=S["groq_rr"])
                if t:
                    for x in S.archive:
                        if x["id"] == m["id"]:
                            x["title"] = t
                    st.rerun()
                else:
                    st.error(gerr or "Groq could not title this.")
            if c.button("Delete", key="dl_%s" % m["id"], use_container_width=True):
                S.archive = [x for x in S.archive if x["id"] != m["id"]]
                st.rerun()

else:  # translate
    LANGS_FROM = {"auto": "Auto detect", "hr": "Croatian", "en": "English",
                  "de": "German"}
    LANGS_TO = {"hr": "Croatian", "en": "English", "de": "German"}

    st.markdown("<span class='muted'>Speak or upload audio. Transcribe it, "
                "translate it, and hear the translation read aloud with the "
                "words highlighted. A speech to speech translator with the text "
                "in the middle.</span>", unsafe_allow_html=True)

    lc1, lc2 = st.columns(2)
    fk = list(LANGS_FROM)
    S.tr_from = fk[lc1.selectbox("From", range(len(fk)),
                                 format_func=lambda i: LANGS_FROM[fk[i]],
                                 index=fk.index(S.tr_from))]
    tk = list(LANGS_TO)
    S.tr_to = tk[lc2.selectbox("To", range(len(tk)),
                               format_func=lambda i: LANGS_TO[tk[i]],
                               index=tk.index(S.tr_to))]

    pc1, pc2 = st.columns(2)
    tx_opts = ["Groq Whisper (free)", "AssemblyAI"]
    tx_i = pc1.radio("Transcribe with", tx_opts,
                     index=0 if S.tx_provider == "groq" else 1)
    S.tx_provider = "groq" if tx_i == tx_opts[0] else "assemblyai"
    tl_opts = ["Groq (free)", "Google"]
    tl_i = pc2.radio("Translate with", tl_opts,
                     index=0 if S.tl_provider == "groq" else 1)
    S.tl_provider = "groq" if tl_i == tl_opts[0] else "google"

    sx = st.radio("Spoken voice", ["Female", "Male"],
                  index=0 if S.tr_sex == "F" else 1, horizontal=True)
    S.tr_sex = "F" if sx == "Female" else "M"

    rec = st.audio_input("Record")
    up = st.file_uploader("or upload audio",
                          type=["wav", "mp3", "m4a", "ogg", "webm", "flac", "aac"])
    audio_src = rec or up

    def _audio():
        if audio_src is None:
            return None, None
        return audio_src.getvalue(), getattr(audio_src, "name", "recording.wav")

    def _src_lang():
        return None if S.tr_from == "auto" else S.tr_from

    def do_transcribe():
        data, name = _audio()
        if not data:
            st.warning("Record or upload some audio first.")
            return None
        with st.spinner("Transcribing with %s..."
                        % ("AssemblyAI" if S.tx_provider == "assemblyai" else "Whisper")):
            text, err = engine.transcribe(data, name, S.tx_provider,
                                          groq_keys(), aai_keys(),
                                          language=_src_lang())
        if err or text is None:
            st.error(err or "Transcription produced nothing.")
            return None
        st.session_state["tr_src"] = text
        return text

    def do_translate(text):
        if not (text or "").strip():
            st.warning("Nothing to translate yet.")
            return None
        S["groq_rr"] = S.get("groq_rr", 0) + 1
        with st.spinner("Translating to %s with %s..."
                        % (LANGS_TO[S.tr_to],
                           "Google" if S.tl_provider == "google" else "Groq")):
            out, err = engine.translate_text(text, S.tr_from, S.tr_to,
                                             S.tl_provider, groq_keys(),
                                             google_keys(), start=S["groq_rr"])
        if err or not out:
            st.error(err or "Translation produced nothing.")
            return None
        st.session_state["tr_out"] = out
        return out

    def do_speak(text):
        if not (text or "").strip():
            st.warning("Nothing to speak yet.")
            return
        voice = engine.voice_for_lang(S.tr_to, S.tr_sex)
        with st.spinner("Reading the %s translation aloud..." % LANGS_TO[S.tr_to]):
            clips, err = synth_voice(text, voice)
        if err or not clips:
            st.error(err or "Could not speak this.")
            return
        S.tr_clips = clips

    b1, b2 = st.columns(2)
    if b1.button("Transcribe", use_container_width=True):
        do_transcribe()
        st.rerun()
    if b2.button("Transcribe, translate & speak", type="primary",
                 use_container_width=True):
        t = do_transcribe()
        if t is not None:
            tl = do_translate(t)
            if tl is not None:
                do_speak(tl)
        st.rerun()

    copy_paste_bar(TRANS_PH, "tsc")
    st.text_area("Transcript", key="tr_src", height=130, placeholder=TRANS_PH)
    if st.button("Translate text", use_container_width=True):
        do_translate(st.session_state.get("tr_src", ""))
        st.rerun()

    copy_paste_bar(TRANSL_PH, "tsl")
    st.text_area("Translation", key="tr_out", height=130, placeholder=TRANSL_PH)
    if st.button("Speak translation", type="primary", use_container_width=True):
        do_speak(st.session_state.get("tr_out") or st.session_state.get("tr_src", ""))
        st.rerun()

    if S.tr_clips:
        st.markdown("<span class='muted'>Translation, %d sentences, spoken in %s."
                    "</span>" % (len(S.tr_clips), LANGS_TO[S.tr_to]),
                    unsafe_allow_html=True)
        st.iframe(build_player(S.tr_clips, current_settings()), height=560)


# ---------- remember look and playback settings, and the archive ----------
persist_settings()
persist_archive()
persist_auth()
