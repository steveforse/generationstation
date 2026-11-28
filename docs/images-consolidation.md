# One Images page (plan, agreed 2026-11-27; built, one picture per model on the Mac still to check by eye)

The picture models get one shared page, as Speech, Decide and Chat have: one sidebar entry named **Images** (the group is called Pictures today, and that word goes everywhere: the Models page group, the quality chart, docs), a dropdown over the running image models, and a form built from the chosen model. Video and Music follow later.

## How the models differ today

| Model | Where | Quality control | Negative prompt | Notes |
| --- | --- | --- | --- | --- |
| Qwen Image 2.1 | Mac, Windows | two presets: Turbo (8 steps, about 20 s) and full (30 guided steps, about 100 s) | full preset only | Qwen Research Licence: personal use only |
| Qwen-Image 2512 | Mac | one preset, 20 guided steps, about 270 s, needs about 37 GiB | yes | Apache-2.0 |
| Z-Image Turbo | Mac | one preset, 9 steps, about 18 s | no | Apache-2.0 |
| MiniMax H3 "A picture" and "Edit pictures" tabs | Windows only; H3 is a video model | its own quality and size fields | n/a | the only model that edits pictures |

All three Mac models are one plugin (`qwen_image`) with one form, so today they show a "Quality" field that the Mac workers ignore (the preset decides) and an "Avoid" field that two of the three ignore.

## Design

1. **Capabilities per model**, like `speech` on the speech plugins: `image` on the plugin (and narrowed per runtime where presets differ): which shapes it offers, whether a negative prompt does anything, whether "Quality" is a real control or the preset decides, whether it can start from pictures (edit), and a sentence of prompt guidance (Qwen: put lettering in quotes; Z-Image: its own habits). The page shows only what the chosen model uses.
2. **Roles** (prompt, shape, negative, seed, quality, pictures) carry what was typed from one model to another; what the new model has no place for is named and kept for the way back.
3. **Dropdown** of running image models with the licence word, the typical time per picture and the memory it needs, so a heavy model is chosen on purpose.
4. **Quality ranking and licence** stay on the Models page; nothing moves there but the group's name.
5. **"Use these settings"** on a result from another image model switches the model and carries the roles, as on Speech.
6. **Chat**: the per-model picture tools become one `make_image` tool whose description lists the running models and what each takes (negative prompt, editing); the assistant's model guide is generated from the same capabilities.
7. **Sidebar**: Images joins Chat, Decide, Meeting notes and Speech as an entry (Pictures group removed); Video and Music keep their sections until they are consolidated.
8. **No redirects**, as before: `modelRoute` sends image models to the Images page.

## Decided

H3's picture tabs (Windows only) appear on the Images page when H3 runs; its clip tabs and clip results stay on its own Video page. Nothing on the Mac is affected.

The dropdown shows the licence only. Time per picture and memory stay on the Models page and the model's details; they would have repeated what is there.

## Checks

Fixture tests for the form logic (capabilities, carry-over, hidden fields), backend tests for the declarations and the `make_image` tool, then one picture per model through the app on the Mac.

## Added after checking the models' own commands (2026-11-27)

The first form only described what the old one had. Each mflux command also takes a custom width and height, a starting picture with a strength (`--image PATH STRENGTH`) and a step count; these are now in the form for the Mac models (the Windows worker has only the four shapes). The starting picture is on Z-Image Turbo only (preset option `start_picture`): the Qwen models repaint the picture and ignore the prompt at any strength, checked 2026-11-27. Not added: guidance (preset-specific, no float field), LoRA styles, scheduler, the experimental small text encoder; instruction editing and multi-picture references need edit weights that are not installed.
