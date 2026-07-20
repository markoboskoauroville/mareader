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

Reading comfort: three themes (night, sepia, day), five fonts including a dyslexia
friendly option, adjustable text size and line spacing, a focus mode, and full
control over the sentence highlight, word highlight, and word font colours. Speed,
volume, gap between sentences, loop, autoplay, and a per voice timing nudge.

Export builds a zip with one mp3 per sentence, the plain text, and a manifest of
word timings. Re-upload that zip in the Offline tab to play it back with no
resynthesis. A session archive keeps pasted texts while the app is open, with an
optional Gemini key for AI titles and one line summaries.

## Files

    streamlit_app.py     the Streamlit app (entry point)
    engine.py            text cleaning, voices, alignment, waveform, edge-tts
    karaoke.py           the embedded HTML/JS word highlighting player
    requirements.txt     Python dependencies
    packages.txt         system packages (ffmpeg) for Streamlit Cloud
    .streamlit/config.toml   dark theme

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
no persistent per user folder. The archive lives in your session, and exports
download to your device rather than to a Downloads folder. Everything else, the
voices, the per word timing, the highlighting, and the offline playback, works
the same.
