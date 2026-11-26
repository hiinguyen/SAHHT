# Art brief: redraw a hero's parts with an image AI

This is the text to give an image AI together with the files of `build/<hero>_kit/`.
Fill in the DESIGN block, then paste the PROMPT block.
Do the sheets one at a time, and always attach `reference/pose_idle.png` so the AI sees how the parts fit together.

## Files to attach

- `sheets/sheet_01.png` (and `sheet_02.png`...): the parts to redraw, one per cell.
- `reference/pose_idle.png`: the whole hero assembled, for proportions and style.
- `reference/pose_attack.png`: a second pose, so the AI sees the hands and arms in use.

## What comes back

- The redrawn sheet, saved as `build/<hero>_kit/redrawn/sheet_01.png` (same file name).
- Same pixel size as the original: 1920 x 1536.
- Parts stay in the same cells, same position inside the cell, same orientation and size.
- Flat grey background `#C8C8C8` stays flat grey (the tool removes it, the original shape is used as the cut-out).

Then run:

```
python3 -m tools.art_kit import ironman build/ironman_kit build/ironman_new/ironman
```

## DESIGN block (fill in)

```
Hero: Iron Man (armored hero, chibi game proportions)
Main armor color: <for example deep crimson red>
Trim / accent color: <for example gold>
Glow color (lights, eyes, chest, joints): <for example white-cyan>
Chest emblem: <for example arc reactor ring, or keep the current "m" logo>
Surface style: <for example glossy metal with sharp highlights>
Mood: <for example heroic, clean, slightly cartoonish>
```

## PROMPT block

```
You are redrawing the armor parts of a 2D game hero for a mobile game with a cut-out (paper doll) animation system.
The attached sheet contains 19 separate armor parts on a flat grey background, laid out on a grid of 5 columns and 4 rows.
The attached "pose" image shows the same parts assembled into the full character, so you can see what each part is.

Redraw EVERY part on the sheet in the new design below.

DESIGN
{paste the DESIGN block here}

HARD RULES (the animation breaks if any of these is violated)
1. Keep the grid exactly: same image size (1920 x 1536), same 5 x 4 cells, every part in the same cell.
2. Keep each part's silhouette, outline, position inside its cell, orientation and size unchanged. Only change colors, materials, panel lines, lights and surface detail.
3. Do not move, rotate, mirror, merge, add or remove parts. Leave the empty cell empty.
4. Keep the flat grey background (#C8C8C8). No shadows on the background, no frames, no labels, no text, no watermark.
5. Do not draw anything that crosses outside a part's own shape. Parts must not touch each other.
6. Use one consistent style across all parts: same light direction (from the top left), same outline weight, same level of detail, same palette. Parts that connect (shoulder, arm, forearm, hand, thigh, boot) must look like they belong to one suit.
7. Keep the hand and the glove shapes readable: finger count and pose stay the same.

STYLE
Clean 2D game illustration, hand-painted look, crisp dark outline, soft cel shading with strong highlights, high contrast so the parts stay readable at small size on a phone.

Output: one image, the full sheet, same size and layout as the input.
```

## Tips

- If the AI changes the layout or image size, ask again with: "Same layout, same size, same positions. Only recolor and re-detail each part."
- If a part comes back with a changed shape, it is clipped to the original shape, so small drifts are harmless, large ones show as missing pieces.
- Generate two or three variants of the sheet and pick the best; do not mix cells from different variants unless the style matches.
- Skill effects (explosions, rings, glows) are not in these sheets. They are recolored by code later, so the new glow color matches.
