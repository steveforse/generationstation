# One Video page (plan, proposed 2026-11-27; nothing built yet)

The video models get one shared page, as Chat, Decide, Speech, Images and Music have: one sidebar entry named **Video** (the Video section goes away, and with it the last section in the sidebar), a dropdown over the running video models with the licence, capability declarations per model, what was typed carried across when you switch, and one `make_video` chat tool instead of one tool per model and way.

## How the models differ today

| | Wan 2.2 5B | FastMetal-QAD (5B, 14B) | LongCat-Video | LTX-2.5 | MiniMax H3 (Mac) | MiniMax H3 (Windows) |
| --- | --- | --- | --- | --- | --- | --- |
| Licence | work (Apache-2.0) | work (Apache-2.0) | work (MIT) | personal | personal | personal |
| Ways today | description, first picture | description | description | description, first picture | description, first and last picture | description, first and last picture, references (pictures, videos, audio), plus its picture tabs (on Images) |
| Length options | short, very short (1.4 s at most) | short, medium, long (up to 5 s) | very short to long (about 0.6 to 4 s) | 2, 4 or 5 s | 3, 5 or 10 s | 5, 10 or 15 s |
| Shape | landscape, portrait, square | landscape, portrait | 832x480 only | landscape, portrait, square | three shapes | five shapes, custom size, match picture |
| Quality control | none | speed: full or fast | none | quick or sharp | draft or standard, plus a resolution | extreme to turbo, plus resolution up to 1080p |
| Sound | none | none | none | made with the picture | none | sounds and music fields, audio references |
| Negative prompt | yes (advanced) | no | no | no | no | no |
| Time (measured) | 1.4 s clip in 70 to 100 s | 5B 2 s in 38 s, 14B in 92 s | 0.6 s in 43 s | 4 s in 32 s (quick) | 5 s at 480p in about 3 min (draft), 16 min (standard) | not on this Mac |

## What each model can do that the form does not offer yet

Read from each tool's own command line, not from memory (the Images and Music work showed that forms hide real capabilities, and that a capability must be tried before it goes in the form).

- **LTX-2.5** (`ltx-2-mlx`) has far more than text and first picture: `keyframe` (interpolate between a start and an end picture, each with a strength), `extend` (add frames before or after an existing video), `retake` (regenerate a time segment of a video), `a2v` (make a video from an audio file and a prompt), `lipdub` (experimental), IC-LoRA control, and `generate --image` taking several pictures. `extend`, `retake` and `a2v` are marked beta.
- **LongCat-Video** has image-to-video (`i2v`) and video continuation (`cont`, which adds new frames to an existing clip) in the driver we already ship; the plugin exposes only text-to-video. Continuation chained is how it makes long videos.
- **Wan 2.2 5B** (`mlx_video.models.wan_2.generate`) takes steps, guidance, noise shift, a scheduler (euler, dpm++, unipc), LoRAs and a frame count; the form has a fixed pair of lengths and a negative prompt.
- **FastMetal** has no picture input in the scripts we run (not tried).
- **H3 on the Mac** runs the first/last-frame checkpoint only; the reference mode needs a checkpoint that is not installed.

## Design

1. **Capabilities per model** (`video` on the plugin, like `speech`, `image` and `music`): how it can start (description, first picture, first and last picture, references, an existing video to extend or to redo a part of), what the length choices are in seconds, whether it makes sound, which quality and shape choices it has. The form shows only what the model has.
2. **Roles** carry what was typed from one model to another: prompt, shape, length, quality, resolution, negative prompt, sounds, music, seed, first picture, last picture, references, source video, strength and section. What the new model has no place for is named on the page and kept for the way back.
3. **Length in seconds**: every length option declares its seconds, so a "5 s" chosen on one model becomes the nearest length on another (a model with only "short" and "very short" gets the nearer one).
4. **Ways of starting as tabs** where a model has several (as ACE-Step has on Music): *From a description*, *From a picture* (first picture, and last where the model takes one), and, where a model has them, *From references*, *Extend a clip* and *Redo part of a clip*. A model with one way has no tab bar.
5. **Result actions**: *Use as first picture* on a clip (the browser takes its last frame, so the next clip continues from where this one ended, on any model that starts from a picture) and *Use as source clip* (for extend, continuation and retake), as *Use as source song* does on Music.
6. **Dropdown** of running video models with the licence word; time and memory stay on the Models page.
7. **Sound**: the page says whether the chosen model makes sound; the sounds and music fields exist only on the models that take them.
8. **Quality ranking** (arena Elo) and licence stay on the Models page; only the group's name and the sidebar change.
9. **"Use these settings"** on a result from another video model switches the model and carries the roles, as on Speech, Images and Music.
10. **Chat**: the per-model video tools (several per model today) become one `make_video` tool whose description lists the running models and what each takes, generated from the same capabilities. The assistant guide is updated.
11. **Images on H3 (Windows)**: its picture tabs already live on the Images page and stay there; only its clip tabs move to this page, as today.
12. **Sidebar**: Video becomes an entry between Speech and the rest, alphabetical with the others; no section is left.
13. **No redirects**: `modelRoute` sends video models to the Video page.

## Not in this pass

- LTX `a2v`, `lipdub`, IC-LoRA and the training commands.
- LoRAs and the solver choice on Wan.
- FastMetal picture input, Wan 2.2 A14B, H3's reference checkpoint on the Mac.
- A timeline or editing view: clips are made and joined one at a time through the result actions.

## Checks

1. Fixture tests for the form logic (capabilities, carry-over, tabs, hidden fields, the result actions), backend tests for the declarations and the `make_video` tool.
2. **Before a feature goes in the form, try it on the real model**: LTX keyframes (do both pictures show in the result), extend (before and after, does the new part continue the clip) and retake (is only the segment changed); LongCat image-to-video (the earlier test with a mismatched picture was garbage, and the worker now crops it; re-test) and continuation (is the join smooth); the last-frame hand-off on two models. Record time and memory for each.
3. One clip per model through the app on the Mac; H3 on the Windows desktop (the page's form for it must still work).

## Decisions needed

- Whether LTX extend and retake go in this pass (recommended: yes, behind the checks above, dropped if the results are poor; they are beta in the tool).
- Whether LongCat's image-to-video and continuation go in this pass (recommended: yes, if the re-test is good).
- Whether *Use as first picture* (last frame of a clip) is wanted. It is cheap and works on every model that starts from a picture.
