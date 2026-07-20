# -*- coding: utf-8 -*-
"""
EdgeReader  v1 (a)

A Streamlit port of MA Reader Web. Paste any text, pick one of 26 Microsoft Edge
neural voices across 13 languages, and it speaks the text sentence by sentence
while highlighting each word in time with the voice. Word timing is measured from
the real audio waveform with ffmpeg, the same DaVinci style engine MA Reader used.

Runs on free Streamlit Community Cloud. Because that environment is stateless and
shared, the archive lives in your session and exports are offered as a download
rather than written to a phone's Downloads folder.
"""
import io
import json
import time
import zipfile

import streamlit as st

import engine
from karaoke import build_player

APP_NAME = "EdgeReader"
APP_VER = "v1 (a)"

st.set_page_config(page_title=APP_NAME, page_icon="\U0001F525", layout="centered")

# ---------- dark chrome ----------
st.markdown(
    """
    <style>
      .stApp { background:#080a10; color:#cdd0d6; }
      section[data-testid="stSidebar"] { background:#0b0e15; }
      h1,h2,h3,h4 { color:#e6e8ee; letter-spacing:.02em; }
      .ev { position:fixed; top:8px; right:14px; font-size:11px;
            color:#565d6e; letter-spacing:.05em; z-index:1000; }
      .stTextArea textarea { background:#11141d; color:#cdd0d6;
            border:1px solid #1d2230; }
      div[data-baseweb="select"] > div { background:#11141d; border-color:#1d2230; }
      .stButton>button { background:#11141d; color:#cdd0d6; border:1px solid #1d2230; }
      .stButton>button:hover { border-color:#7d5cff; color:#fff; }
      .stDownloadButton>button { background:#11141d; color:#cdd0d6; border:1px solid #1d2230; }
      .accent { color:#7d5cff; }
      .cyan { color:#3fb9c8; }
      .muted { color:#7c8294; font-size:13px; }
    </style>
    <div class="ev">%s %s</div>
    """ % (APP_NAME, APP_VER),
    unsafe_allow_html=True,
)

# ---------- session defaults ----------
def _init():
    s = st.session_state
    s.setdefault("enabled_langs", list(engine.DEFAULT_LANGS))
    s.setdefault("voice_id", 1)
    s.setdefault("theme", "night")
    s.setdefault("font", "serif")
    s.setdefault("size", 21)
    s.setdefault("lineheight", 3)
    s.setdefault("speed", 1.0)
    s.setdefault("gap", 0.0)
    s.setdefault("volume", 100)
    s.setdefault("loop", False)
    s.setdefault("autoplay", False)
    s.setdefault("focus", False)
    s.setdefault("wordhl", True)
    s.setdefault("offset_ms", 0)
    s.setdefault("sent_rgb", [255, 217, 59])
    s.setdefault("word_rgb", [226, 59, 78])
    s.setdefault("font_rgb", [255, 255, 255])
    s.setdefault("gemini_key", "")
    s.setdefault("clips", None)
    s.setdefault("clips_text", "")
    s.setdefault("clips_voice", None)
    s.setdefault("clips_title", "")
    s.setdefault("archive", [])
    s.setdefault("pastebox", "")


_init()
S = st.session_state


# ---------- cached synthesis ----------
@st.cache_data(show_spinner=False, max_entries=64)
def _synth_cached(text, voice_edge):
    clips, err = engine.synth_sentences(text, voice_edge)
    return clips, err


def voice_edge_of(vid):
    v = engine.VOICES.get(vid)
    return v[0] if v else engine.VOICES[1][0]


def voice_name_of(vid):
    v = engine.VOICES.get(vid)
    return v[1] if v else ""


def voice_vkey_of(vid):
    v = engine.VOICES.get(vid)
    return v[4] if v else "ukF"


def enabled_voice_options():
    """(labels, ids) for the picker, only for enabled languages."""
    ids, labels = [], []
    for v in engine.voices_list():
        lang = v["lang"]
        if lang in S.enabled_langs:
            ids.append(v["id"])
            labels.append("%s  \u00b7  %s" % (v["name"], v["label"]))
    if not ids:  # nothing enabled: fall back to full list so a voice is pickable
        for v in engine.voices_list():
            ids.append(v["id"])
            labels.append("%s  \u00b7  %s" % (v["name"], v["label"]))
    return labels, ids


def current_settings():
    return {
        "theme": S.theme, "font": S.font, "size": S.size,
        "lineheight": S.lineheight, "speed": S.speed, "gap": S.gap,
        "volume": S.volume, "loop": S.loop, "autoplay": S.autoplay,
        "focus": S.focus, "wordhl": S.wordhl, "offsetMs": S.offset_ms,
        "sentRGB": S.sent_rgb, "wordRGB": S.word_rgb, "fontRGB": S.font_rgb,
    }


def build_export_zip(clips, title, vid):
    """One EdgeReader export: manifest.json + text.txt + clips/sNNNN.mp3."""
    buf = io.BytesIO()
    sents = []
    duration = 0.0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for c in clips:
            clip = "s%04d.mp3" % c["i"]
            z.writestr("clips/" + clip, c["mp3"])
            sents.append({"i": c["i"], "text": c["text"], "clip": clip,
                          "dur": c["dur"], "words": c["words"]})
            duration += c["dur"]
        z.writestr("text.txt", "\n".join(c["text"] for c in clips) + "\n")
        manifest = {
            "app": "EdgeReader", "schema": "edgereader/1",
            "title": title or "Untitled", "voice": voice_name_of(vid),
            "vkey": voice_vkey_of(vid),
            "lang": engine.VOICES[vid][2] if vid in engine.VOICES else "",
            "created": int(time.time()),
            "duration": round(duration, 3),
            "sentences": sents,
        }
        z.writestr("manifest.json",
                   json.dumps(manifest, ensure_ascii=False, indent=1))
    buf.seek(0)
    return buf.getvalue()


def clips_from_zip(raw):
    """Rebuild the player payload from an EdgeReader export zip."""
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        clips = []
        for sen in manifest.get("sentences", []):
            clip = sen.get("clip", "")
            mp3 = z.read("clips/" + clip)
            clips.append({"i": sen.get("i", 0), "text": sen.get("text", ""),
                          "mp3": mp3, "words": sen.get("words", []),
                          "dur": sen.get("dur", 0.0)})
    return manifest, clips


# =========================================================================
# Sidebar: voice + all settings
# =========================================================================
with st.sidebar:
    st.markdown("### Voice")
    labels, ids = enabled_voice_options()
    if S.voice_id not in ids:
        S.voice_id = ids[0]
    sel = st.selectbox("Reading voice", labels,
                       index=ids.index(S.voice_id), label_visibility="collapsed")
    S.voice_id = ids[labels.index(sel)]

    with st.expander("Languages", expanded=False):
        st.caption("Tick a language to add its two voices to the picker.")
        cat = engine.langs_catalogue()
        cols = st.columns(2)
        chosen = []
        for n, lg in enumerate(cat):
            with cols[n % 2]:
                lbl = lg["label"]
                if lg["native"]:
                    lbl += "  (%s)" % lg["native"]
                on = st.checkbox(lbl, value=(lg["key"] in S.enabled_langs),
                                 key="lang_%s" % lg["key"])
                if lg.get("uses"):
                    st.caption("Can be used for: " + lg["uses"])
                if on:
                    chosen.append(lg["key"])
        S.enabled_langs = chosen

    with st.expander("Reading look", expanded=True):
        S.theme = st.radio("Theme", ["night", "sepia", "day"],
                           index=["night", "sepia", "day"].index(S.theme),
                           horizontal=True)
        S.font = st.selectbox(
            "Font", ["serif", "sans", "book", "mono", "dyslexic"],
            index=["serif", "sans", "book", "mono", "dyslexic"].index(S.font))
        S.size = st.slider("Text size", 14, 40, S.size)
        S.lineheight = st.slider("Line spacing", 1, 5, S.lineheight)
        S.focus = st.checkbox("Focus mode (dim other sentences)", S.focus)

    with st.expander("Playback", expanded=False):
        speeds = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5,
                  1.75, 2.0, 2.25, 2.5]
        S.speed = st.select_slider("Speed", speeds, value=S.speed)
        S.gap = st.slider("Gap between sentences (s)", 0.0, 3.0, S.gap, 0.1)
        S.volume = st.slider("Volume", 0, 100, S.volume, 5)
        S.loop = st.checkbox("Loop", S.loop)
        S.autoplay = st.checkbox("Auto-play on open", S.autoplay)

    with st.expander("Word highlight colours", expanded=False):
        S.wordhl = st.checkbox("Highlight the word being read", S.wordhl)

        def rgb_row(label, key):
            st.caption(label)
            c = st.columns(3)
            v = S[key]
            r = c[0].number_input("R", 0, 255, v[0], key=key + "_r",
                                  label_visibility="collapsed")
            g = c[1].number_input("G", 0, 255, v[1], key=key + "_g",
                                  label_visibility="collapsed")
            b = c[2].number_input("B", 0, 255, v[2], key=key + "_b",
                                  label_visibility="collapsed")
            S[key] = [int(r), int(g), int(b)]
            st.markdown(
                "<div style='height:14px;border-radius:4px;background:rgb(%d,%d,%d)'></div>"
                % (r, g, b), unsafe_allow_html=True)

        rgb_row("Sentence highlight background", "sent_rgb")
        rgb_row("Word highlight background", "word_rgb")
        rgb_row("Highlighted word font colour", "font_rgb")

        S.offset_ms = st.slider(
            "Timing nudge (ms) \u00b7 later \u2192 earlier", -300, 300,
            S.offset_ms, 20)

    with st.expander("Gemini (optional AI titles)", expanded=False):
        st.caption("Paste a Google Gemini API key to auto name and summarise "
                   "archived texts. It stays in your session only.")
        S.gemini_key = st.text_input("Gemini API key", S.gemini_key,
                                     type="password")


# =========================================================================
# Header + tabs
# =========================================================================
st.markdown("# \U0001F525 %s" % APP_NAME)
st.markdown("<span class='muted'>Fire the word. Paste text, it reads aloud "
            "and highlights every word in time.</span>", unsafe_allow_html=True)

tab_read, tab_archive, tab_offline, tab_help = st.tabs(
    ["Read", "Archive", "Offline", "Help"])


# ---------- READ ----------
with tab_read:
    txt = st.text_area(
        "Paste a text to read",
        value=S.pastebox, height=200,
        placeholder="Paste or type anything. Links and Markdown are stripped "
                    "automatically, so only the words are read.")
    S.pastebox = txt

    c1, c2, c3 = st.columns([1, 1, 1])
    read_click = c1.button("Read it", type="primary", use_container_width=True)
    save_click = c2.button("Save to archive", use_container_width=True)
    clear_click = c3.button("Clear", use_container_width=True)

    if clear_click:
        S.pastebox = ""
        S.clips = None
        st.rerun()

    if save_click and txt.strip():
        title = next((ln.strip()[:60] for ln in txt.splitlines() if ln.strip()),
                     "Untitled")
        S.archive.insert(0, {"id": int(time.time() * 1000), "title": title,
                             "text": txt, "chars": len(txt),
                             "created": int(time.time()),
                             "ai_title": "", "summary": ""})
        st.success("Saved to archive: %s" % title)

    if read_click:
        clean = engine.clean_text(txt)
        if not clean.strip():
            st.warning("Paste some text first.")
        else:
            vedge = voice_edge_of(S.voice_id)
            with st.spinner("Speaking sentence by sentence and measuring word "
                            "timing from the audio..."):
                clips, err = _synth_cached(clean, vedge)
            if err or not clips:
                st.error(err or "Nothing was produced.")
            else:
                S.clips = clips
                S.clips_text = clean
                S.clips_voice = S.voice_id
                S.clips_title = next(
                    (ln.strip()[:60] for ln in txt.splitlines() if ln.strip()),
                    "Untitled")

    if S.clips:
        stale = (S.clips_voice != S.voice_id)
        if stale:
            st.info("Voice changed. Press Read it again to hear %s."
                    % voice_name_of(S.voice_id))
        eng = S.clips[0].get("engine", "edge") if S.clips else "edge"
        src = "waveform (ffmpeg)" if eng == "pcm" else "edge word marks"
        st.caption("%d sentences \u00b7 voice %s \u00b7 timing: %s"
                   % (len(S.clips), voice_name_of(S.clips_voice), src))

        html = build_player(S.clips, current_settings(), title=S.clips_title)
        st.components.v1.html(html, height=650, scrolling=False)

        zip_bytes = build_export_zip(S.clips, S.clips_title, S.clips_voice)
        st.download_button(
            "Export (mp3 clips + text + manifest .zip)",
            data=zip_bytes,
            file_name="%s.zip" % (S.clips_title or "edgereader"),
            mime="application/zip", use_container_width=True)
        st.caption("The zip plays back in the Offline tab, or unzips to per "
                   "sentence mp3 files.")
    else:
        if not engine.ffmpeg_available():
            st.caption("Note: ffmpeg was not found, so word timing falls back to "
                       "the engine's own marks. Add a packages.txt with ffmpeg "
                       "for waveform accurate timing on Streamlit Cloud.")


# ---------- ARCHIVE ----------
with tab_archive:
    st.markdown("### Archive")
    st.caption("Saved in this session. Open re-speaks a text in the current "
               "voice; download from the Read tab to keep it permanently.")
    q = st.text_input("Search", "", key="arch_q")
    items = S.archive
    if q.strip():
        ql = q.lower()
        items = [m for m in items if ql in m["title"].lower()
                 or ql in m.get("summary", "").lower()]

    if not items:
        st.info("No saved texts yet. Paste something in Read and press "
                "Save to archive.")
    else:
        if st.button("Delete all", key="arch_delall"):
            S.archive = []
            st.rerun()
        for m in items:
            with st.container(border=True):
                head = m["title"]
                if m.get("ai_title"):
                    head = m["ai_title"]
                st.markdown("**%s**" % head)
                meta = "%d characters" % m["chars"]
                if m.get("summary"):
                    st.caption(m["summary"])
                st.caption(meta)
                cc = st.columns(4)
                if cc[0].button("Open", key="open_%s" % m["id"]):
                    S.pastebox = m["text"]
                    clean = engine.clean_text(m["text"])
                    with st.spinner("Speaking..."):
                        clips, err = _synth_cached(clean, voice_edge_of(S.voice_id))
                    if not err and clips:
                        S.clips = clips
                        S.clips_text = clean
                        S.clips_voice = S.voice_id
                        S.clips_title = m["title"]
                        st.success("Loaded. Open the Read tab to play.")
                    else:
                        st.error(err or "Could not speak this.")
                if cc[1].button("Delete", key="del_%s" % m["id"]):
                    S.archive = [x for x in S.archive if x["id"] != m["id"]]
                    st.rerun()
                if S.gemini_key.strip() and cc[2].button(
                        "AI title", key="ai_%s" % m["id"]):
                    obj, gerr = engine.gemini_title_summary(
                        engine.clean_text(m["text"]), S.gemini_key)
                    if obj:
                        for x in S.archive:
                            if x["id"] == m["id"]:
                                x["ai_title"] = obj["ai_title"]
                                x["summary"] = obj["summary"]
                        st.rerun()
                    else:
                        st.error(gerr or "Gemini could not summarise this.")


# ---------- OFFLINE ----------
with tab_offline:
    st.markdown("### Offline playback")
    st.caption("Upload an EdgeReader export .zip to play it back with the same "
               "word highlighting, no synthesis needed.")
    up = st.file_uploader("EdgeReader export (.zip)", type=["zip"])
    if up is not None:
        try:
            manifest, clips = clips_from_zip(up.read())
            st.caption("%s \u00b7 %d sentences \u00b7 voice %s"
                       % (manifest.get("title", "Untitled"),
                          len(clips), manifest.get("voice", "")))
            html = build_player(clips, current_settings(),
                                title=manifest.get("title", ""))
            st.components.v1.html(html, height=650, scrolling=False)
        except Exception as e:
            st.error("That did not look like an EdgeReader export: %s" % e)


# ---------- HELP ----------
with tab_help:
    st.markdown("### How EdgeReader works")
    st.markdown(
        "Paste any text in the **Read** tab and press **Read it**. EdgeReader "
        "strips links and Markdown, splits the text into sentences, and speaks "
        "each sentence with your chosen Microsoft Edge neural voice. As it "
        "plays, the current sentence is highlighted and each word lights up in "
        "time with the voice.")
    st.markdown("### Voices and languages")
    st.markdown(
        "There are 13 languages, each with a female and a male neural voice, "
        "for 26 in all. Pick which languages appear in the voice picker under "
        "**Languages** in the sidebar. Croatian can also read Dalmatian and "
        "\u010cakav\u0161tina, and Hindi can read Sanskrit written in "
        "Devanagari.")
    st.markdown("### Word timing")
    st.markdown(
        "Timing is measured from the audio itself. After a sentence is spoken, "
        "EdgeReader listens to the finished clip, finds where speech really "
        "starts, ends, and rises after each pause, and pins every word to that "
        "waveform, the way a caption tool such as DaVinci Resolve stays glued "
        "to speech. This needs ffmpeg, which Streamlit Cloud installs from a "
        "packages.txt file. Without it, the engine's own word marks are used. "
        "If the highlight feels early or late on a voice, nudge it with the "
        "timing slider in the sidebar.")
    st.markdown("### Export and offline")
    st.markdown(
        "**Export** builds a zip holding one small mp3 per sentence, the plain "
        "text, and a manifest with the word timings. Because Streamlit Cloud is "
        "a shared server, the zip downloads to your device rather than writing "
        "to a Downloads folder. Re-upload that zip in the **Offline** tab to "
        "play it back without speaking it again.")
    st.markdown("### Archive")
    st.markdown(
        "Texts you save live in your browser session while the app is open. To "
        "keep one permanently, export it. With a Gemini key you can add an AI "
        "title and one line summary to archived texts.")
    st.markdown("### Reading comfort")
    st.markdown(
        "Three themes (night, sepia, day), five fonts including a dyslexia "
        "friendly option, adjustable text size and line spacing, a focus mode "
        "that dims the sentences you are not reading, and full control over the "
        "sentence highlight, word highlight, and word font colours.")
    st.caption("%s %s \u00b7 ported from MA Reader Web" % (APP_NAME, APP_VER))
