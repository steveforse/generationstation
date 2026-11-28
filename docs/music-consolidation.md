# One Music page (plan, proposed 2026-11-27; nothing built yet)

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
- **YuE2** has the melody planning option and a sampling step count; no reference audio in this port.

## Design

1. **Capabilities per model** (`music` on the plugin, like `speech` and `image`): whether lyrics are required, whether an instrumental is possible, the length control (a fixed list, a range, or none), whether it takes a language, tempo, key, time signature, and which song-editing tabs it has. The form shows only what the model has.
2. **Roles** carry what was typed from one model to another: style, lyrics, instrumental, length, language, tempo, key, time signature, seed, source song, strength, section start and end. What the new model has no place for is named on the page and kept for the way back.
3. **One Instrumental switch** instead of "leave the lyrics empty". YuE2 takes blank lyrics (whitespace) and simply sings nothing, so the switch works on all three (reported 2026-11-27 from use; confirmed on the real model while building, and the YuE2 form stops requiring lyrics).
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
