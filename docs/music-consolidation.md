# One Music page (plan agreed and built 2026-11-27; chat tool and sidebar tested; a listening check per model left)

The three song models get one shared page, as Chat, Decide, Speech and Images have: one sidebar entry named **Music** (the Music group goes away), a dropdown over the running song models with the licence, capability declarations per model, what was typed carried across when you switch, and one `make_song` chat tool instead of one tool per model.

## How the models differ today

| | YuE2 3B | ACE-Step 1.5 (turbo) | MiniMax Music 3 |
| --- | --- | --- | --- |
| Where | Mac and Windows | Mac | Mac |
| Licence | CC BY-NC (personal use only) | MIT (work) | Community licence (work, owner's reading) |
| Style text | 400 characters | 400 (model says under 512) | 600 |
| Lyrics | required (no instrumental) | optional, empty makes an instrumental | optional, empty makes an instrumental |
| Length | not chosen: the song is as long as its lyrics (about real time to make) | pick 30, 60 or 120 s (model takes 10 to 600) | pick a maximum of 30 to 180 s (model takes up to 360); may end sooner |
| Language | from the lyrics | pick one of 10 | from the lyrics |
| Time to make | about as long as the song | 30 s of music in about 10 s | 30 s of music in about 70 s |
| Memory | 14 GiB | 22 GiB (21 GiB peak at 2 minutes) | 20 GiB |
| Extras in the form today | melody planning (full, melody, off), seed | seed | seed |

## What each model can do that the form does not offer yet

Checked in each model's own code, not from memory (the Images work showed that a form that only mirrors the old one hides real capabilities, and also that a capability must be tried before it goes in the form).

- **ACE-Step 1.5 turbo** takes, in the same call we already make: a **tempo** (30 to 300 BPM), a key (such as "C Major" or "Am"), a time signature (2/4, 3/4, 4/4, 6/8), any length from 10 to 600 s, and three more tasks that work on a song you give it: **cover** (a new version of a song in another style or with new lyrics, strength 0 to 1), **repaint** (redo a section by start and end seconds, which also extends a song) and a reference audio for style. Extract, lego and complete need the base model, which is not installed.
- **MiniMax Music 3** takes a step count (1 to 30, default 30; it goes under More options) and lengths up to 360 s. It has no reference audio, cover or repaint.
- **YuE2** has the melody planning option and a sampling step count. Corrected 2026-11-27: it also makes a **new version of a song** (mlx-Yue's `cover`): SheetSage2 and MERT2 read the melody and structure of a recording into a score, and the song model sings it again with a new style and lyrics. It does not keep the sound of the original. (An earlier version of this plan said the port had no reference audio; that came from reading only the request fields.)

## Design

1. **Capabilities per model** (`music` on the plugin, like `speech` and `image`): whether lyrics are required, whether an instrumental is possible, the length control (a fixed list, a range, or none), whether it takes a language, tempo, key, time signature, and which song-editing tabs it has. The form shows only what the model has.
2. **Roles** carry what was typed from one model to another: style, lyrics, instrumental, length, language, tempo, key, time signature, seed, source song, strength, section start and end. What the new model has no place for is named on the page and kept for the way back.
3. **Empty lyrics mean an instrumental** on all three models (no separate switch). Checked on the real YuE2: blank lyrics did not stay silent (the model invented words and sang them), so for YuE2 the worker sends instrumental sections instead (`[Intro: Instrumental]`, `[Instrumental Break]`, `[Outro: Instrumental]`), which gave a mostly instrumental piece with an occasional vocal moment. The YuE2 form no longer requires lyrics.
4. **Lyrics help for all three**: chips that insert the structure tags ([Verse], [Chorus], [Bridge], [Intro], [Outro]) at the cursor, a running count of characters and an estimate of the length the lyrics will make. A "write lyrics for me" button is a possible later addition (it would ask a running chat model).
5. **Length keeps today's choices**: ACE-Step 30, 60 or 120 s; MiniMax 30, 60, 120 or 180 s (a maximum); YuE2 set by the lyrics. Those are what has been measured. Longer lengths are added only if a measurement shows they fit the memory estimate, and not otherwise (the models accept 600 s and 360 s, but nobody has run them here).
6. **ACE-Step tabs** (only when it runs): **Song** (the default), **New version of a song** (cover: pick or upload a song, style and optional new lyrics, strength) and **Redo a section** (repaint: pick or upload a song, start and end seconds, what to put there). The source song can be an earlier result ("Use as source" on a song in the results list) or an uploaded file; the Speech page's audio picker and playback already exist.
7. **Dropdown** of running song models with the licence word; time and memory stay on the Models page and the model's details.
8. **Quality ranking** (SongBench) and licence stay on the Models page; only the group's name and the sidebar change.
9. **"Use these settings"** on a result from another song model switches the model and carries the roles, as on Speech and Images.
10. **Chat**: the per-model song tools become one `make_song` tool (style, lyrics or instrumental, length, language, tempo, key, seed, a source song for a new version, which model). Its description lists the running models and what each takes, generated from the same capabilities; the assistant guide is updated.
11. **Sidebar**: Music becomes an entry between Meeting notes and Speech, with its icon; Video keeps its section until it is consolidated.
12. **No redirects**: `modelRoute` sends song models to the Music page.

## Not in this pass

- ACE-Step extract, lego and complete (base model, about 4 GB more, not installed).
- A song-editing tab for MiniMax or YuE2 (no such feature).
- Batch (several takes at once), the planning model's own settings, and the XL 4B diffusion model.
- Lyrics-writing button (later, once the page works).

## Checks

1. Fixture tests for the form logic (capabilities, carry-over, the Instrumental switch, hidden fields, tab changes), backend tests for the declarations and the `make_song` tool.
2. **Before a feature goes in the form, try it on the real model**: ACE-Step tempo, key and time signature (does the result follow them, measured by listening and by an automatic tempo estimate), cover at several strengths (does a different style come through, as the fox test showed for pictures), repaint (a section replaced, the rest unchanged, and extending past the end), and a long song on ACE-Step and MiniMax to find the memory peak and the longest length that fits in the estimate.
3. One song per model through the app on the Mac; YuE2 on the Windows desktop (the page's form for it must still work without the Mac-only fields).

## Decided (2026-11-27)

- Tempo, key and time signature go in the ACE-Step form (tempo in the main form, key and time signature under More options).
- Cover and repaint are in this pass, behind the real-model checks above.
- MiniMax's step count goes under More options.
- Lengths stay as they are today; no new ceilings until measured.

## Built and measured (2026-11-27)

- ACE-Step tempo, cover and repaint were tried on the real model first. Tempo 140 measured 140.6 BPM. Cover at strength 30 and 80 changed the sound (spectral centroid 4291 Hz to 2789 and 2316 Hz) and 80 kept more of the harmony (chroma correlation 0.83, against 0.45 at 30). Repaint of 10 to 20 s left the rest identical to the original (correlation 1.00) and changed the section; an end past the end of the song extended it (30 s to 45 s). Key was not verified by ear.
- MiniMax steps work (8 steps 38 s, 30 steps 69 s for 30 s of music, both with clear words).
- Lengths were left as they were.
- The page's carry-over exposed a bug that also applied to the other consolidated pages: when the chosen model changed, the form first opened on the old model's tab name, mounted blank and reported its blank fields over the draft; it now opens on the new model's first tab.
- Not done: a listening check per model, YuE2 on the Windows desktop.

## YuE2 new version of a song (added 2026-11-27)

- Needs `mido`, `mir-eval`, `pretty-midi` and `scipy` in the mlx-Yue environment (`uv pip install --python ~/ai/tools/mlx-Yue/.venv/bin/python mido==1.3.3 mir-eval==0.8.2 pretty-midi==0.2.11.post0 "scipy>=1.13,<2"`) and two downloads into the Hugging Face cache, both CC BY-NC 4.0 like YuE2 itself: `m-a-p/SheetSage2` (0.23 GB, revision eab522a8) and `m-a-p/MERT-v2-FullSong` (2.5 GB, revision d8ba1c74). The worker runs offline, so a missing download is reported as missing.
- On the real model through the app: a 30 s MiniMax song became a 95 s new version in 53 s (the length follows the lyrics and the score, not the source). The sung words came out as written, the key (F minor) and tempo (75 BPM) of the source were kept, and the sound differed (the spectral centroid fell from 4367 to 2637 Hz). From the command line, the melody-only task made a 55 s version of the same source in 34 s.
- It is a field of YuE2's single form ("Start from a song"), not a tab: YuE2's own planning field is called `mode`, which would collide with a tab key and with the stored inputs of earlier songs. The Music page treats it as the cover way of starting. It needs lyrics (the model's own instrumental option, `cover --instrumental`, calls a module this checkout lacks) and a melody planning other than "off".
- The Windows worker has no melody reader, so the field is dropped there.
- Plain instrumental YuE2 songs stay unreliable: in four tests, with blank lyrics, with instrumental-section placeholders and with "no vocals, no singing" in the style, the transcription still heard sung words in the first minute. The page says so.
