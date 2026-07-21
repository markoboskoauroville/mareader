# EdgeReader

Paste any text, pick a Microsoft Edge neural voice, and EdgeReader reads it aloud
sentence by sentence while highlighting each word in time with the voice. It is a
Streamlit port of MA Reader Web, built to run on free Streamlit Community Cloud.

## What it does

Thirteen languages, each with a female and a male neural voice, for twenty six in
all. English, Croatian, Bosnian, Serbian, Macedonian, Albanian, Slovenian,
German, French, Italian, Tamil, Hindi, and Spanish. Croatian also reads Dalmatian
and Cakavstina, and Hindi reads Sanskrit in Devanagari.

Word timing is measured from the real audio waveform with ffmpeg, the same
DaVinci style approach MA Reader used, so the highlighted word lands exactly when
the voice says it. Without ffmpeg it falls back to the engine's own word marks.

The interface is minimal: three tabs, Paste, Reading, and History. You paste in
the first and press Read, the app speaks it and switches to Reading on its own,
and it files the text in History automatically. History keeps only the text,
never the audio, so any past piece can be spoken again with its Read with TTS
button. There the transport sits at the top so it stays in reach on long texts,
and the words flow below and scroll on their own. A fullscreen button opens a
distraction free ebook mode where the controls vanish and only the reading
remains. The progress bar runs across the whole text, with elapsed and total time
and a sentence counter beside it.

Reading comfort lives in the sidebar: three themes (night, sepia, day), eleven
fonts with sans serif first (sans is the default, since serifs are harder to read
on screen) and a legible option for dyslexia, adjustable text size and line
spacing, a focus mode, and an auto scroll that can keep the current sentence
pinned to the top so your eye rests on one spot. Full R G B control over the
sentence highlight, the word highlight, and the word text colour, with a live
sample. Speed, volume, gap between sentences, loop, autoplay, and a per voice
timing nudge.

Export builds a zip with one mp3 per sentence, the plain text, and a manifest of
word timings. Load that zip again from the sidebar to play it back with no
resynthesis. The archive keeps your saved pieces between visits, stored in the
browser, with an optional Gemini key for AI titles.

## Translate (speech to speech)

The Translate tab is a small speech to speech translator with the text shown in
the middle. Record with the built in microphone or upload an audio file, then the
app transcribes it, translates it, and reads the translation aloud with the words
highlighted. Transcription uses Groq Whisper (free) or AssemblyAI (paid, with
universal-3-pro then universal-2 as fallback). Translation uses Groq (free) or
Google (paid). Languages are Croatian, English, and German, plus Auto detection
for the source, and the spoken translation uses a neural voice in the target
language. Every step falls back across your keys, and the transcript and
translation are editable before you speak them.

## Files

    streamlit_app.py     the Streamlit app (entry point)
    engine.py            text cleaning, voices, alignment, waveform, edge-tts, Groq
    karaoke.py           the embedded HTML/JS word highlighting player
    requirements.txt     Python dependencies
    packages.txt         system packages (ffmpeg) for Streamlit Cloud
    .streamlit/config.toml          dark theme
    .streamlit/secrets.toml.example example Groq keys, copy to secrets.toml

## AI titles with Groq (optional)

Saved pieces can be titled automatically by Groq, which reads the whole text and
returns one short title. Provide your Groq keys as a TOML array. Locally, copy
`.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill it in. On
Streamlit Community Cloud, open the app, then Settings, then Secrets, and paste:

    groq_keys = [
      "gsk_your_first_key",
      "gsk_your_second_key",
      "gsk_your_third_key",
    ]

Several keys are supported and rotated across requests, so if one hits a rate
limit the next is tried. Never commit your real `secrets.toml`; it is gitignored.
The whole archive can also be downloaded as a single json file and imported back,
which sidesteps the browser storage size limit for long term keeping.

## Deploy on Streamlit Community Cloud

1. Create a new GitHub repository and upload every file in this folder, keeping
   the `.streamlit` folder and its `config.toml` inside.
2. Go to share.streamlit.io and sign in with GitHub.
3. Click New app, choose your repository and branch, and set the main file path
   to `streamlit_app.py`.
4. Deploy. The first build installs ffmpeg from `packages.txt` and the Python
   packages from `requirements.txt`, then the app comes online at a public URL.

## Run locally

    pip install -r requirements.txt
    streamlit run streamlit_app.py

For waveform accurate timing locally, install ffmpeg too (for example
`brew install ffmpeg` on macOS or `pkg install ffmpeg` on Termux).

## Notes on the Streamlit Cloud environment

Streamlit Cloud is stateless and shared, so unlike the Termux original there is
no persistent per user folder. Instead, your look and playback settings and your
saved archive pieces are stored in the browser (a cookie for settings, chunked
cookies for the archive) and read back on your next visit. Very long or very many
saved pieces are capped by cookie size, so the oldest may not persist; export
those to keep them. Clearing browser data or using a private window resets both.
Exports download to your device rather than to a Downloads folder. Everything
else, the voices, the per word timing, the highlighting, and the offline playback,
works
the same.
