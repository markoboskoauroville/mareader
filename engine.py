# -*- coding: utf-8 -*-
"""
EdgeReader engine (v1)

Ported straight from MA Reader Web's server.py. Everything that turns text into
spoken, word timed audio lives here, with no Flask and no local library: text is
cleaned, split into sentences, each sentence is spoken by edge-tts into its own
mp3 with word timings, and (when ffmpeg is present) every word is pinned to the
real decoded waveform the way a caption tool does.

Streamlit calls synth_sentences() to get, for a whole text, a list of clips with
per word timings ready to hand to the karaoke player.
"""
import os, re, json, time, shutil, asyncio, random
import subprocess, unicodedata, urllib.request, urllib.error, urllib.parse

# ---------- languages & voices ----------
# Every language group ships exactly two Microsoft neural voices, one female and
# one male. LANGS is the source of truth; VOICES (the flat id -> tuple map the
# rest of the engine speaks) is derived from it below. Some voices can stand in
# for a dialect that has no neural voice of its own; that is written as a plain
# "uses" note, never as its own button.
LANGS = [
    {"key": "en", "label": "English (UK)", "native": "",
     "vkeys": ("ukF", "ukM"),
     "female": ("en-GB-SoniaNeural", "Sonia"),
     "male":   ("en-GB-RyanNeural", "Ryan")},
    {"key": "hr", "label": "Croatian", "native": "Hrvatski",
     "uses": "Dalmatian, \u010cakav\u0161tina",
     "vkeys": ("hrF", "hrM"),
     "female": ("hr-HR-GabrijelaNeural", "Gabrijela"),
     "male":   ("hr-HR-SreckoNeural", "Srecko")},
    {"key": "bs", "label": "Bosnian", "native": "Bosanski",
     "vkeys": ("bsF", "bsM"),
     "female": ("bs-BA-VesnaNeural", "Vesna"),
     "male":   ("bs-BA-GoranNeural", "Goran")},
    {"key": "sr", "label": "Serbian", "native": "Srpski",
     "vkeys": ("srF", "srM"),
     "female": ("sr-RS-SophieNeural", "Sophie"),
     "male":   ("sr-RS-NicholasNeural", "Nicholas")},
    {"key": "mk", "label": "Macedonian", "native": "Makedonski",
     "vkeys": ("mkF", "mkM"),
     "female": ("mk-MK-MarijaNeural", "Marija"),
     "male":   ("mk-MK-AleksandarNeural", "Aleksandar")},
    {"key": "sq", "label": "Albanian", "native": "Shqip",
     "vkeys": ("sqF", "sqM"),
     "female": ("sq-AL-AnilaNeural", "Anila"),
     "male":   ("sq-AL-IlirNeural", "Ilir")},
    {"key": "sl", "label": "Slovenian", "native": "Sloven\u0161\u010dina",
     "vkeys": ("slF", "slM"),
     "female": ("sl-SI-PetraNeural", "Petra"),
     "male":   ("sl-SI-RokNeural", "Rok")},
    {"key": "de", "label": "German", "native": "Deutsch",
     "vkeys": ("deF", "deM"),
     "female": ("de-DE-KatjaNeural", "Katja"),
     "male":   ("de-DE-ConradNeural", "Conrad")},
    {"key": "fr", "label": "French", "native": "Fran\u00e7ais",
     "vkeys": ("frF", "frM"),
     "female": ("fr-FR-DeniseNeural", "Denise"),
     "male":   ("fr-FR-HenriNeural", "Henri")},
    {"key": "it", "label": "Italian", "native": "Italiano",
     "vkeys": ("itF", "itM"),
     "female": ("it-IT-ElsaNeural", "Elsa"),
     "male":   ("it-IT-DiegoNeural", "Diego")},
    {"key": "ta", "label": "Tamil", "native": "\u0ba4\u0bae\u0bbf\u0bb4\u0bcd",
     "vkeys": ("taF", "taM"),
     "female": ("ta-IN-PallaviNeural", "Pallavi"),
     "male":   ("ta-IN-ValluvarNeural", "Valluvar")},
    {"key": "hi", "label": "Hindi", "native": "\u0939\u093f\u0928\u094d\u0926\u0940",
     "uses": "Sanskrit",
     "vkeys": ("hiF", "hiM"),
     "female": ("hi-IN-SwaraNeural", "Swara"),
     "male":   ("hi-IN-MadhurNeural", "Madhur")},
    {"key": "es", "label": "Spanish", "native": "Espa\u00f1ol",
     "vkeys": ("esF", "esM"),
     "female": ("es-ES-ElviraNeural", "Elvira"),
     "male":   ("es-ES-AlvaroNeural", "Alvaro")},
]

DEFAULT_LANGS = ["en", "hr"]

VOICES = {}
LANG_BY_KEY = {}


def _build_voices():
    vid = 1
    for lg in LANGS:
        LANG_BY_KEY[lg["key"]] = lg
        for sex, slot, vk in (("F", "female", lg["vkeys"][0]),
                              ("M", "male", lg["vkeys"][1])):
            edge, name = lg[slot]
            VOICES[vid] = (edge, name, lg["key"], sex, vk)
            vid += 1


_build_voices()
VKEYS = {v[4] for v in VOICES.values()}
VOICE_BY_VKEY = {v[4]: v for v in VOICES.values()}
UNIT_CAP = 320


def voice_label(langkey, sex):
    lg = LANG_BY_KEY.get(langkey)
    base = lg["label"] if lg else langkey
    return base + (" female" if sex == "F" else " male")


def voices_list():
    """Flat list the picker uses: id, vkey, name, lang, sex, label."""
    return [{"id": i, "vkey": v[4], "name": v[1], "lang": v[2], "sex": v[3],
             "label": voice_label(v[2], v[3])}
            for i, v in sorted(VOICES.items())]


def langs_catalogue():
    """Full language list for the settings panel: each with its two voices and
    an optional 'uses' note."""
    by_key = {}
    for vid, v in sorted(VOICES.items()):
        by_key.setdefault(v[2], []).append(
            {"id": vid, "name": v[1], "sex": v[3], "vkey": v[4]})
    out = []
    for lg in LANGS:
        out.append({"key": lg["key"], "label": lg["label"],
                    "native": lg.get("native", ""),
                    "uses": lg.get("uses", ""),
                    "voices": by_key.get(lg["key"], [])})
    return out


# ---------- text -> sentences -> units ----------
_SENT_RE = re.compile(r"(?<=[.!?\u2026])\s+")


def split_sentences(text):
    spans, start = [], 0
    for m in _SENT_RE.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    if start < len(text):
        spans.append((start, len(text)))
    return [(a, b) for a, b in spans if text[a:b].strip()]


def split_units(text, cap=UNIT_CAP):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    units = []
    for a, b in split_sentences(text):
        s = a
        while b - s > cap:
            cut = text.rfind(" ", s, s + cap)
            if cut <= s:
                cut = s + cap
            if text[s:cut].strip():
                units.append((s, cut))
            s = cut
            while s < b and text[s] in " \n\t":
                s += 1
        if b > s and text[s:b].strip():
            units.append((s, b))
    return units


# ---------- clean: strip links + Markdown so only plain words are read ----------
_FENCE_RE = re.compile(r"^\s*(?:```+|~~~+).*$", re.M)
_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_AUTOLINK_RE = re.compile(r"<((?:https?|ftp|mailto):[^>\s]+)>", re.I)
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_REFLINK_RE = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_REFDEF_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s+\S.*$", re.M)
_URL_RE = re.compile(r"(?:(?:https?|ftp)://|www\.)[^\s<>)\]}\"']+", re.I)
_MAILTO_RE = re.compile(r"\bmailto:[^\s<>)\]}\"']+", re.I)
_HTML_RE = re.compile(r"</?[A-Za-z][^>]*>")
_CODE_RE = re.compile(r"`+([^`]*)`+")
_EMPH_AST_RE = re.compile(r"(\*\*|\*|~~)(?=\S)(.+?)(?<=\S)\1", re.S)
_EMPH_US_RE = re.compile(r"(?<![\w])(__|_)(?=\S)(.+?)(?<=\S)\1(?![\w])", re.S)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
_QUOTE_RE = re.compile(r"^\s{0,3}>+\s?")
_BULLET_RE = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+")
_RULE_RE = re.compile(r"^\s{0,3}(?:(?:[-*_]\s*){3,}|=+)\s*$")


def clean_text(text):
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _FENCE_RE.sub("", text)
    text = _IMG_RE.sub("", text)
    text = _AUTOLINK_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _REFLINK_RE.sub(r"\1", text)
    text = _REFDEF_RE.sub("", text)
    text = _URL_RE.sub("", text)
    text = _MAILTO_RE.sub("", text)
    text = _HTML_RE.sub("", text)
    text = _CODE_RE.sub(r"\1", text)
    for _ in range(3):
        new = _EMPH_AST_RE.sub(r"\2", text)
        new = _EMPH_US_RE.sub(r"\2", new)
        if new == text:
            break
        text = new
    out = []
    for ln in text.split("\n"):
        if _RULE_RE.match(ln):
            continue
        ln = _HEADING_RE.sub("", ln)
        ln = _QUOTE_RE.sub("", ln)
        ln = _BULLET_RE.sub(r"\1", ln)
        if "|" in ln:
            stripped = ln.strip()
            if stripped and set(stripped) <= set("|:- "):
                continue
            ln = ln.replace("|", " ")
        out.append(ln)
    text = "\n".join(out)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\[\s*\]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    text = re.sub(r" *\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sentences_of(text):
    """Cleaned text -> list of sentence strings, the unit the reader speaks."""
    text = clean_text(text)
    units = split_units(text)
    return [text[a:b].strip() for a, b in units]


# ---------- align edge-tts word timings to exact character ranges ----------
_TOKEN_RE = re.compile(r"\S+")


def _norm(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c.lower() for c in s if c.isalnum())


def align_tokens(sentence, bounds, total=None):
    """For every visible word run in `sentence`, return its start/end char
    offsets and its start time `t` and end time `d` in seconds. Times come from
    edge-tts word boundaries where they match; elsewhere they are interpolated
    so the sweep is always monotonic, spans the whole clip and never collapses
    onto one word."""
    tokens = [(m.start(), m.end()) for m in _TOKEN_RE.finditer(sentence)]
    out = [{"s": a, "e": b, "t": None, "d": None} for (a, b) in tokens]
    n = len(tokens)
    if not n:
        return []
    bn = [(_norm(x["w"]), x["t"], x.get("d", 0.0)) for x in bounds]
    bn = [(w, t, d) for (w, t, d) in bn if w]
    bi, nB = 0, len(bn)
    for ti, (a, b) in enumerate(tokens):
        tok = _norm(sentence[a:b])
        if not tok:
            continue
        start_bi = bi
        guard = 0
        found = False
        while bi < nB and guard < 6:
            bw = bn[bi][0]
            if tok.startswith(bw) or bw.startswith(tok) or bw == tok:
                found = True
                break
            bi += 1
            guard += 1
        if not found:
            bi = start_bi
            continue
        out[ti]["t"] = bn[bi][1]
        last_t, last_d = bn[bi][1], bn[bi][2]
        acc = ""
        while bi < nB:
            acc += bn[bi][0]
            last_t, last_d = bn[bi][1], bn[bi][2]
            bi += 1
            if acc == tok or not tok.startswith(acc):
                break
        out[ti]["d"] = last_t + last_d

    known = [(i, o["t"]) for i, o in enumerate(out) if o["t"] is not None]
    widths = [max(1, b - a) for (a, b) in tokens]

    if not known:
        span = total if (total and total > 0.1) else (0.32 * n)
        acc = 0.0
        wsum = float(sum(widths))
        for i, w in enumerate(widths):
            out[i]["t"] = span * (acc / wsum)
            acc += w
            out[i]["d"] = span * (acc / wsum)
        return out

    fi, ft = known[0]
    for i in range(fi):
        out[i]["t"] = ft
    for (i0, t0), (i1, t1) in zip(known, known[1:]):
        gap = i1 - i0
        if gap <= 1:
            continue
        seg = widths[i0 + 1:i1]
        ws = float(sum(seg)) or 1.0
        acc = 0.0
        for k, j in enumerate(range(i0 + 1, i1)):
            acc += seg[k]
            out[j]["t"] = t0 + (t1 - t0) * (acc / ws) - (t1 - t0) * (seg[k] / ws)
    li, lt = known[-1]
    tail_end = total if (total and total > lt + 0.05) else lt + 0.45 * (n - li)
    rest = list(range(li + 1, n))
    if rest:
        seg = [widths[j] for j in rest]
        ws = float(sum(seg)) or 1.0
        acc = 0.0
        for k, j in enumerate(rest):
            out[j]["t"] = lt + (tail_end - lt) * (acc / ws)
            acc += seg[k]

    prev = 0.0
    for o in out:
        if o["t"] is None or o["t"] < prev:
            o["t"] = prev
        prev = o["t"]
    for i in range(n):
        nxt = out[i + 1]["t"] if i + 1 < n else (
            total if (total and total > out[i]["t"]) else out[i]["t"] + 0.4)
        if out[i]["d"] is None or out[i]["d"] <= out[i]["t"] or out[i]["d"] > nxt:
            out[i]["d"] = nxt
        if out[i]["d"] <= out[i]["t"]:
            out[i]["d"] = nxt
    return out


# ---------- waveform alignment (the v11 engine, ffmpeg from stdin) ----------
_FFMPEG = shutil.which("ffmpeg")
_ENV_SR = 8000
_ENV_WIN_MS = 10


def ffmpeg_available():
    return bool(_FFMPEG)


def _pcm_env_bytes(mp3_bytes):
    """Decode mp3 bytes to mono 8 kHz 16-bit via ffmpeg on stdin, return
    (frames, dur). frames is the RMS energy of every 10 ms window."""
    if not _FFMPEG:
        return None, 0.0
    try:
        p = subprocess.run(
            [_FFMPEG, "-v", "quiet", "-i", "pipe:0",
             "-ac", "1", "-ar", str(_ENV_SR), "-f", "s16le", "-"],
            input=mp3_bytes, capture_output=True, timeout=90)
        raw = p.stdout
    except Exception:
        return None, 0.0
    if not raw or len(raw) < _ENV_SR // 5:
        return None, 0.0
    import array
    a = array.array("h")
    a.frombytes(raw[:len(raw) // 2 * 2])
    n = _ENV_SR * _ENV_WIN_MS // 1000
    frames = []
    for i in range(0, len(a) - n + 1, n):
        s = 0
        for j in range(i, i + n):
            v = a[j]
            s += v * v
        frames.append((s / n) ** 0.5)
    return frames, len(a) / float(_ENV_SR)


def _speech_span(env, thr):
    W = _ENV_WIN_MS / 1000.0
    onset = None
    for i in range(len(env) - 2):
        if env[i] > thr and env[i + 1] > thr and env[i + 2] > thr:
            onset = i * W
            break
    last = None
    for i in range(len(env) - 1, 0, -1):
        if env[i] > thr and env[i - 1] > thr:
            last = (i + 1) * W
            break
    return onset, last


_MIN_PAUSE_FR = 9


def _rise_points(env, thr, low):
    W = _ENV_WIN_MS / 1000.0
    rises = []
    quiet_run = 10 ** 6
    for i, v in enumerate(env):
        if v < low:
            quiet_run += 1
            continue
        if v > thr and quiet_run >= _MIN_PAUSE_FR:
            ahead = env[i:i + 5]
            if sum(1 for x in ahead if x > thr * 0.7) >= 3:
                rises.append(i * W)
        if v > thr:
            quiet_run = 0
    return rises


def _match_anchors(word_ts, rises):
    n, m = len(word_ts), len(rises)
    if not n or not m:
        return []
    SKIP = 0.18
    CAP = 0.45
    dp = [[0.0] * (n + 1) for _ in range(m + 1)]
    for j in range(1, m + 1):
        dp[j][0] = dp[j - 1][0] + SKIP
    for j in range(1, m + 1):
        for i in range(1, n + 1):
            best = dp[j][i - 1]
            c = dp[j - 1][i] + SKIP
            if c < best:
                best = c
            pair = abs(word_ts[i - 1] - rises[j - 1])
            if pair <= CAP:
                c = dp[j - 1][i - 1] + pair
                if c < best:
                    best = c
            dp[j][i] = best
    out = []
    j, i = m, n
    while j > 0 and i > 0:
        pair = abs(word_ts[i - 1] - rises[j - 1])
        if pair <= CAP and abs(dp[j][i] - (dp[j - 1][i - 1] + pair)) < 1e-9:
            out.append((i - 1, rises[j - 1]))
            j -= 1
            i -= 1
        elif abs(dp[j][i] - (dp[j - 1][i] + SKIP)) < 1e-9:
            j -= 1
        else:
            i -= 1
    out.reverse()
    return out


def refine_tokens(mp3_bytes, tokens):
    """Re-anchor word times onto the real decoded waveform. Returns
    (tokens, dur, changed); on any trouble the original tokens come back."""
    if not tokens:
        return tokens, 0.0, False
    env, dur = _pcm_env_bytes(mp3_bytes)
    if not env or dur <= 0.2:
        return tokens, 0.0, False
    peak = max(env)
    if peak <= 0:
        return tokens, dur, False
    thr = peak * 0.10
    low = peak * 0.05
    onset, last = _speech_span(env, thr)
    if onset is None or last is None or last - onset < 0.15:
        return tokens, dur, False

    t0 = float(tokens[0].get("t", 0.0))
    t1 = max(float(t.get("d", t.get("t", 0.0))) for t in tokens)
    if t1 - t0 < 0.05:
        return tokens, dur, False

    a = (last - onset) / (t1 - t0)
    if not (0.5 < a < 2.0):
        a = 1.0
    b = onset - a * t0
    ref = []
    for t in tokens:
        nt = a * float(t.get("t", 0.0)) + b
        nd = a * float(t.get("d", t.get("t", 0.0))) + b
        ref.append({"s": t.get("s", 0), "e": t.get("e", 0), "t": nt, "d": nd})

    rises = _rise_points(env, thr, low)
    word_ts = [w["t"] for w in ref]
    pairs = _match_anchors(word_ts, rises)
    anchors = [(word_ts[i], r) for (i, r) in pairs]
    anchors.append((max(ref[-1]["d"], anchors[-1][0] + 0.01 if anchors else 0),
                    min(last, dur)))
    clean = []
    for (x, y) in anchors:
        if not clean or (x > clean[-1][0] + 1e-3 and y > clean[-1][1] + 1e-3):
            clean.append((x, y))
    if len(clean) >= 2:
        def warp(x):
            if x <= clean[0][0]:
                return clean[0][1] + (x - clean[0][0])
            for (x0, y0), (x1, y1) in zip(clean, clean[1:]):
                if x <= x1:
                    return y0 + (x - x0) * (y1 - y0) / (x1 - x0)
            xN, yN = clean[-1]
            return yN + (x - xN)
        for w in ref:
            w["t"] = warp(w["t"])
            w["d"] = warp(w["d"])

    prev = -1.0
    for w in ref:
        if w["t"] <= prev:
            w["t"] = prev + 0.01
        prev = w["t"]
    for i, w in enumerate(ref):
        nxt = ref[i + 1]["t"] if i + 1 < len(ref) else min(last + 0.05, dur)
        if w["d"] <= w["t"] or w["d"] > nxt:
            w["d"] = nxt
        if w["d"] <= w["t"]:
            w["d"] = w["t"] + 0.05
        w["t"] = round(w["t"], 3)
        w["d"] = round(w["d"], 3)
    return ref, dur, True


# ---------- mp3 duration fallback (pure-python frame sum) ----------
_BR_V2L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
_BR_V1L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_SR_TAB = {0: {0: 11025, 1: 12000, 2: 8000}, 3: {0: 44100, 1: 48000, 2: 32000},
           2: {0: 22050, 1: 24000, 2: 16000}}


def mp3_duration_bytes(data):
    try:
        n = len(data)
        i = 0
        if data[:3] == b"ID3" and n > 10:
            size = ((data[6] & 0x7f) << 21) | ((data[7] & 0x7f) << 14) | \
                   ((data[8] & 0x7f) << 7) | (data[9] & 0x7f)
            i = 10 + size
        total = 0.0
        frames = 0
        while i + 4 <= n:
            if data[i] != 0xFF or (data[i + 1] & 0xE0) != 0xE0:
                i += 1
                continue
            b1, b2 = data[i + 1], data[i + 2]
            ver = (b1 >> 3) & 3
            layer = (b1 >> 1) & 3
            if layer != 1 or ver == 1:
                i += 1
                continue
            br_i = (b2 >> 4) & 0xF
            sr_i = (b2 >> 2) & 3
            pad = (b2 >> 1) & 1
            if br_i == 0 or br_i == 15 or sr_i == 3:
                i += 1
                continue
            br = (_BR_V1L3 if ver == 3 else _BR_V2L3)[br_i] * 1000
            sr = _SR_TAB.get(ver, {}).get(sr_i)
            if not sr or not br:
                i += 1
                continue
            spf = 1152 if ver == 3 else 576
            flen = int((spf // 8) * br / sr) + pad
            if flen < 4:
                i += 1
                continue
            total += spf / float(sr)
            frames += 1
            i += flen
        return total if frames else None
    except Exception:
        return None


# ---------- speech (edge-tts) ----------
def _run_async(coro):
    try:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    except RuntimeError:
        return asyncio.run(coro)


# edge-tts talks to Microsoft's free public endpoint. On shared cloud IPs that
# can transiently 403 (rate limit), reset, or hand back empty audio. These are
# not permanent failures, so we retry a few times with exponential backoff and
# jitter before giving up. RETRIES and RETRY_BASE can be tuned by the caller.
RETRIES = 4
RETRY_BASE = 0.8      # seconds; delay is RETRY_BASE * 2**attempt plus jitter
RETRY_CAP = 8.0       # never wait longer than this between attempts


def _is_transient(msg):
    m = (msg or "").lower()
    for sign in ("403", "429", "timeout", "timed out", "temporarily",
                 "reset", "connection", "unavailable", "handshake",
                 "no audio", "empty", "eof", "closed", "ssl"):
        if sign in m:
            return True
    return False


def _edge_stream(text, voice):
    """One attempt at the network call. Returns (mp3_bytes, bounds, error)."""
    import edge_tts

    async def go():
        bounds = []
        buf = bytearray()
        com = edge_tts.Communicate(text, voice)
        async for ch in com.stream():
            if ch["type"] == "audio":
                buf.extend(ch["data"])
            elif ch["type"] == "WordBoundary":
                bounds.append({"t": ch["offset"] / 1e7,
                               "d": ch["duration"] / 1e7, "w": ch["text"]})
        return bytes(buf), bounds

    try:
        mp3_bytes, bounds = _run_async(go())
    except Exception as e:
        return None, None, "TTS failed: %s" % e
    if not mp3_bytes:
        return None, None, "no audio"
    return mp3_bytes, bounds, ""


def synth_one(text, voice, retries=None):
    """Speak one sentence, retrying transient network failures with exponential
    backoff. Returns (mp3_bytes, tokens, total_seconds, engine) or
    (None, None, 0, error_string)."""
    try:
        import edge_tts  # noqa: F401
    except Exception:
        return None, None, 0.0, "edge-tts not installed"

    attempts = RETRIES if retries is None else max(1, retries)
    mp3_bytes, bounds, err = None, None, "no audio"
    for attempt in range(attempts):
        mp3_bytes, bounds, err = _edge_stream(text, voice)
        if not err:
            break
        # a permanent error (bad voice, malformed) will not improve on retry
        if not _is_transient(err) or attempt == attempts - 1:
            break
        delay = min(RETRY_CAP, RETRY_BASE * (2 ** attempt))
        delay += random.uniform(0, delay * 0.5)   # jitter to de-sync callers
        time.sleep(delay)

    if err or not mp3_bytes:
        note = err or "no audio"
        if _is_transient(note):
            note += " (retried %d times; the voice service may be rate " \
                    "limiting this server, try again shortly)" % attempts
        return None, None, 0.0, note

    total = 0.0
    for bnd in bounds:
        end = bnd.get("t", 0.0) + bnd.get("d", 0.0)
        if end > total:
            total = end
    tokens = align_tokens(text, bounds, total or None)

    engine = "edge"
    ref, dur, changed = refine_tokens(mp3_bytes, tokens)
    if changed:
        tokens = ref
        engine = "pcm"
        if dur > 0:
            total = dur
    if total <= 0:
        d = mp3_duration_bytes(mp3_bytes)
        total = d if d else 1.0
    return mp3_bytes, tokens, round(total, 3), engine


def synth_sentences(text, voice, progress=None):
    """Speak a whole text sentence by sentence. `progress` is an optional
    callback(done, total). Returns (clips, error). Each clip is
    {i, text, mp3: bytes, words: [{s,e,t,d}], dur, engine}."""
    sents = sentences_of(text)
    if not sents:
        return [], "Paste some text first."
    clips = []
    n = len(sents)
    for i, s in enumerate(sents):
        mp3, tokens, total, engine = synth_one(s, voice)
        if mp3 is None:
            return None, "Sentence %d failed: %s" % (i + 1, engine)
        clips.append({"i": i, "text": s, "mp3": mp3, "words": tokens,
                      "dur": total, "engine": engine})
        if progress:
            progress(i + 1, n)
    return clips, ""


# ---------- optional Google Gemini: title + one line summary ----------
GEMINI_MODELS = ["gemini-2.5-flash-lite", "gemini-flash-lite-latest",
                 "gemini-flash-latest", "gemini-2.5-flash"]
GEMINI_ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/"
                   "models/%s:generateContent")


def _extract_json(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*", "", text).strip().rstrip("`").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    for op, cl in (("{", "}"), ("[", "]")):
        a = text.find(op)
        b = text.rfind(cl)
        if a >= 0 and b > a:
            try:
                return json.loads(text[a:b + 1])
            except Exception:
                pass
    return None


def gemini_title_summary(text, key):
    """Returns ({ai_title, summary}, error). Cheapest model first, climbing only
    when a cheaper answer does not check out."""
    key = (key or "").strip()
    if not key:
        return None, "No Gemini key provided."
    snippet = text.strip()[:6000]
    prompt = (
        "You label reading material. Read the text and return JSON only, exactly "
        '{"ai_title": "...", "summary": "..."} . ai_title is at most 8 words, no '
        "quotes. summary is ONE sentence, at most 24 words, plain and concrete. "
        "Text follows:\n\n" + snippet)
    last_err = "No model produced a usable answer."
    for model in GEMINI_MODELS:
        url = (GEMINI_ENDPOINT % model) + "?key=" + urllib.parse.quote(key)
        payload = {"contents": [{"parts": [{"text": prompt}]}],
                   "generationConfig": {"temperature": 0.0,
                                        "maxOutputTokens": 256,
                                        "responseMimeType": "application/json"}}
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read().decode("utf-8", "replace")
            obj = json.loads(raw)
            txt = ""
            for cand in obj.get("candidates", []):
                for part in cand.get("content", {}).get("parts", []):
                    txt += part.get("text", "")
            o = _extract_json(txt)
            if isinstance(o, dict) and o.get("ai_title") and o.get("summary"):
                return {"ai_title": str(o["ai_title"])[:80].strip(),
                        "summary": str(o["summary"])[:200].strip()}, ""
            last_err = "%s answered but the result did not check out." % model
            continue
        except urllib.error.HTTPError as e:
            code = e.code
            if code in (400, 401, 403, 429):
                if code == 400:
                    return None, "Gemini rejected the request. Check the key."
                if code in (401, 403):
                    return None, "Gemini key refused (expired, revoked, or no billing)."
                return None, "Gemini quota or rate limit hit."
            last_err = "Gemini error %s." % code
            continue
        except Exception as e:
            last_err = "Gemini request failed: %s" % e
            continue
    return None, last_err


# ---------- Groq: title a whole text, rotating across keys and models ----------
# Groq is OpenAI compatible. The Llama chat models were retired in mid 2026, so
# these default to the OpenAI open models and Kimi K2 that Groq hosts now, with
# a fallback chain so a further deprecation of any one model is survived.
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b",
               "moonshotai/kimi-k2-instruct", "llama-3.3-70b-versatile"]


def _clean_title(t):
    t = (t or "").strip().strip('"').strip("'").strip()
    if t.lower().startswith("title:"):
        t = t[6:].strip()
    t = " ".join(t.split())
    return t.rstrip(".").strip()[:80]


def groq_title(text, keys, start=0):
    """Summarise a whole text into one short title. Tries each key in a rotated
    order (to spread rate limits across the five keys) and each model in turn.
    Returns (title, error)."""
    keys = [k for k in keys if isinstance(k, str) and k.strip()]
    if not keys:
        return None, "No Groq keys provided."
    snippet = text.strip()[:6000]
    sys_msg = "You write concise, descriptive titles for reading material."
    user_msg = ("Give a short title, at most 8 words, that captures what this "
                "text is about. Return only the title as plain text, with no "
                "surrounding quotes and no trailing period.\n\nText:\n" + snippet)
    n = len(keys)
    order = [keys[(start + i) % n] for i in range(n)]
    last = "Groq could not produce a title."
    for key in order:
        advanced_key = False
        for model in GROQ_MODELS:
            payload = {"model": model, "temperature": 0.3, "max_tokens": 40,
                       "messages": [{"role": "system", "content": sys_msg},
                                    {"role": "user", "content": user_msg}]}
            req = urllib.request.Request(
                GROQ_ENDPOINT, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + key.strip()}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    obj = json.loads(r.read().decode("utf-8", "replace"))
                txt = obj["choices"][0]["message"]["content"]
                title = _clean_title(txt)
                if title:
                    return title, ""
                last = "%s returned an empty title." % model
            except urllib.error.HTTPError as e:
                code = e.code
                if code in (401, 403):
                    last = "A Groq key was rejected."
                    advanced_key = True
                    break            # try the next key
                if code == 429:
                    last = "Groq rate limit hit."
                    advanced_key = True
                    break            # rotate to the next key
                if code in (400, 404):
                    last = "Model %s unavailable on Groq." % model
                    continue         # try the next model on the same key
                last = "Groq error %s." % code
                continue
            except Exception as e:
                last = "Groq request failed: %s" % e
                continue
        if not advanced_key:
            # every model failed for reasons other than key/rate; next key anyway
            continue
    return None, last


# ---------- language helpers shared by transcription and translation ----------
LANG_NAMES = {"hr": "Croatian", "en": "English", "de": "German",
              "auto": "the detected source language"}


def lang_name(code):
    return LANG_NAMES.get(code, code)


def voice_for_lang(lang, sex="F"):
    """Pick an edge voice id for a target language, so a translation can be
    spoken in the language it was translated into."""
    lg = LANG_BY_KEY.get(lang) or LANG_BY_KEY.get("en")
    edge, _ = lg["female"] if sex == "F" else lg["male"]
    return edge


_DE_STOP = {"und", "der", "die", "das", "ist", "nicht", "ich", "sie", "mit",
            "auf", "für", "ein", "eine", "zu", "den", "dem", "von", "auch",
            "wird", "wie", "aber", "sind", "war", "haben", "sein", "noch"}
_HR_STOP = {"i", "je", "na", "se", "da", "su", "za", "od", "koji", "ali", "kao",
            "to", "sto", "nije", "sam", "biti", "ovo", "ili", "kroz", "vise",
            "jer", "samo", "kada", "gdje", "ovaj", "bez", "nas", "vas"}
_EN_STOP = {"the", "and", "is", "of", "to", "in", "that", "it", "for", "with",
            "as", "are", "was", "this", "but", "not", "you", "have", "he",
            "she", "they", "we", "at", "on", "be", "or", "an"}


def detect_lang(text):
    """Rough detector across English, German, Croatian for the Auto option.
    Uses diacritics and common words. Returns 'en', 'de', or 'hr'."""
    t = (text or "").lower()
    if not t.strip():
        return "en"
    hr_chars = sum(t.count(c) for c in "\u010d\u0107\u017e\u0161\u0111")  # čćžšđ
    de_chars = sum(t.count(c) for c in "\u00e4\u00f6\u00fc\u00df")        # äöüß
    words = re.findall(r"[a-z\u0161\u0111\u010d\u0107\u017e\u00e4\u00f6\u00fc]+", t)
    de = de_chars * 3 + sum(1 for w in words if w in _DE_STOP)
    hr = hr_chars * 4 + sum(1 for w in words if w in _HR_STOP)
    en = sum(1 for w in words if w in _EN_STOP)
    best_lang, best = "en", en
    for lang, score in (("de", de), ("hr", hr)):
        if score > best:
            best_lang, best = lang, score
    return best_lang if best > 0 else "en"


# ---------- multipart helper (no requests dependency) ----------
def _multipart(fields, filename, filedata, field="file",
               content_type="application/octet-stream"):
    boundary = "EdgeReaderB" + os.urandom(10).hex()
    body = bytearray()
    for k, v in fields.items():
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                 % (boundary, k, v)).encode("utf-8")
    body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
             "Content-Type: %s\r\n\r\n" % (boundary, field, filename, content_type)).encode("utf-8")
    body += filedata + ("\r\n--%s--\r\n" % boundary).encode("utf-8")
    return bytes(body), "multipart/form-data; boundary=" + boundary


# ---------- transcription: Groq Whisper (free) ----------
GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
WHISPER_MODEL = "whisper-large-v3"


def groq_transcribe(audio, filename, keys, language=None):
    """Transcribe audio bytes with Groq Whisper, rotating keys. language may be
    hr, en, de or None (auto). Returns (text, error)."""
    keys = [k for k in keys if isinstance(k, str) and k.strip()]
    if not keys:
        return None, "No Groq keys for Whisper."
    errs = []
    for i, key in enumerate(keys):
        fields = {"model": WHISPER_MODEL, "response_format": "json"}
        if language in ("hr", "en", "de"):
            fields["language"] = language
        body, ctype = _multipart(fields, filename or "audio.wav", audio)
        req = urllib.request.Request(
            GROQ_TRANSCRIBE_URL, data=body, method="POST",
            headers={"Authorization": "Bearer " + key.strip(), "Content-Type": ctype})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            return (data.get("text") or "").strip(), ""
        except urllib.error.HTTPError as e:
            msg = "HTTP %s" % e.code
            try:
                j = json.loads(e.read().decode("utf-8", "replace"))
                msg += ": " + j.get("error", {}).get("message", "")
            except Exception:
                pass
            errs.append("key %d %s" % (i + 1, msg))
        except Exception as e:
            errs.append("key %d %s" % (i + 1, e))
    return None, "Every Groq key failed. " + " | ".join(errs)


# ---------- transcription: AssemblyAI (paid) ----------
AAI_BASE = "https://api.assemblyai.com"
AAI_MODELS = ["universal-3-pro", "universal-2"]


def assemblyai_transcribe(audio, keys, language=None, poll_max=60, poll_sleep=3):
    """Transcribe audio bytes with AssemblyAI: upload, create, poll. Rotates
    keys. Returns (text, error)."""
    keys = [k for k in keys if isinstance(k, str) and k.strip()]
    if not keys:
        return None, "No AssemblyAI keys."
    errs = []
    for i, key in enumerate(keys):
        key = key.strip()
        try:
            up = urllib.request.Request(
                AAI_BASE + "/v2/upload", data=audio, method="POST",
                headers={"authorization": key, "content-type": "application/octet-stream"})
            with urllib.request.urlopen(up, timeout=300) as r:
                upload_url = json.loads(r.read().decode("utf-8", "replace"))["upload_url"]

            body = {"audio_url": upload_url, "speech_models": AAI_MODELS}
            if language in ("hr", "en", "de"):
                body["language_code"] = language
            else:
                body["language_detection"] = True
            tr = urllib.request.Request(
                AAI_BASE + "/v2/transcript", data=json.dumps(body).encode("utf-8"),
                method="POST",
                headers={"authorization": key, "content-type": "application/json"})
            with urllib.request.urlopen(tr, timeout=60) as r:
                tid = json.loads(r.read().decode("utf-8", "replace"))["id"]

            for _ in range(poll_max):
                time.sleep(poll_sleep)
                pr = urllib.request.Request(AAI_BASE + "/v2/transcript/" + tid,
                                            headers={"authorization": key})
                with urllib.request.urlopen(pr, timeout=60) as r:
                    d = json.loads(r.read().decode("utf-8", "replace"))
                if d.get("status") == "completed":
                    return (d.get("text") or "").strip(), ""
                if d.get("status") == "error":
                    raise RuntimeError(d.get("error", "transcription failed"))
            raise TimeoutError("timeout, audio may be too long")
        except urllib.error.HTTPError as e:
            errs.append("key %d HTTP %s" % (i + 1, e.code))
        except Exception as e:
            errs.append("key %d %s" % (i + 1, e))
    return None, "Every AssemblyAI key failed. " + " | ".join(errs)


def transcribe(audio, filename, provider, groq_keys, aai_keys, language=None):
    if provider == "assemblyai":
        return assemblyai_transcribe(audio, aai_keys, language=language)
    return groq_transcribe(audio, filename, groq_keys, language=language)


# ---------- translation: Groq (free) or Google Gemini (paid) ----------
def _translate_prompt(text, src, tgt):
    return ("Translate the following text from %s to %s. Return only the "
            "translation, with no notes and no quotes, and keep it natural.\n\n%s"
            % (lang_name(src), lang_name(tgt), text[:60000]))


def groq_translate(text, src, tgt, keys, start=0):
    keys = [k for k in keys if isinstance(k, str) and k.strip()]
    if not keys:
        return None, "No Groq keys."
    prompt = _translate_prompt(text, src, tgt)
    n = len(keys)
    order = [keys[(start + i) % n] for i in range(n)]
    last = "Groq translation failed."
    for key in order:
        for model in GROQ_MODELS:
            payload = {"model": model, "temperature": 0.2, "max_tokens": 2000,
                       "messages": [{"role": "user", "content": prompt}]}
            req = urllib.request.Request(
                GROQ_ENDPOINT, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "Authorization": "Bearer " + key.strip()}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    obj = json.loads(r.read().decode("utf-8", "replace"))
                out = obj["choices"][0]["message"]["content"].strip().strip('"').strip()
                if out:
                    return out, ""
                last = "%s returned nothing." % model
            except urllib.error.HTTPError as e:
                if e.code in (401, 403, 429):
                    last = "Groq key rejected or rate limited."
                    break
                last = "Groq error %s." % e.code
                continue
            except Exception as e:
                last = "Groq request failed: %s" % e
                continue
    return None, last


def gemini_translate(text, src, tgt, keys, start=0):
    keys = [k for k in keys if isinstance(k, str) and k.strip()]
    if not keys:
        return None, "No Google keys."
    prompt = _translate_prompt(text, src, tgt)
    n = len(keys)
    order = [keys[(start + i) % n] for i in range(n)]
    last = "Google translation failed."
    for key in order:
        for model in GEMINI_MODELS:
            url = GEMINI_ENDPOINT % model
            payload = {"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048}}
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json",
                         "x-goog-api-key": key.strip()}, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    obj = json.loads(r.read().decode("utf-8", "replace"))
                txt = ""
                for cand in obj.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        txt += part.get("text", "")
                txt = txt.strip().strip('"').strip()
                if txt:
                    return txt, ""
                last = "%s returned nothing." % model
            except urllib.error.HTTPError as e:
                if e.code in (400, 401, 403, 429):
                    last = "Google key rejected or rate limited."
                    break
                last = "Google error %s." % e.code
                continue
            except Exception as e:
                last = "Google request failed: %s" % e
                continue
    return None, last


def translate_text(text, src, tgt, provider, groq_keys, google_keys, start=0):
    if not text.strip():
        return None, "Nothing to translate."
    if provider == "google":
        return gemini_translate(text, src, tgt, google_keys, start=start)
    return groq_translate(text, src, tgt, groq_keys, start=start)
