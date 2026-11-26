# Art brief: new Iron Man ultimate, "missile rain"

The skill is made of a few key pose images of the hero and a few effect images.
The game plays them in order and moves them between the poses, like the original ultimate did.
You generate 3 sheets with an image AI, save them in `generated/`, and tell Claude.

## Files to attach to every request

- `reference/ref_01_new_character.png`: the new Iron Man, the look to keep (ignore the cyan flame under the feet, it is drawn separately).
- `reference/ref_00_new_armor_parts.png`: the armor parts of the new look, for color, trim and materials.
- `reference/ref_02_pose_composition_rise.png`, `ref_03_pose_composition_flight.png`, `ref_04_pose_composition_carry.png`: poses of the OLD hero in the old skill. Use them only for how a skill pose is composed (a strong, readable silhouette, the body seen from slightly above). Do not copy the old dark look.
- `reference/ref_06_old_explosion_style.png`: the explosion style of the game (use only for scale and style of fire).

## Storyboard (about 2.7 seconds)

1. Crouch: the hero bends his knees and leans forward, gathering energy.
2. Rise: he shoots straight up, body stretched, legs together.
3. Hover and charge: arms spread wide, the chest reactor glows, the shoulder missile pods flip open.
4. Fire: he throws both arms forward, leans back from the recoil, nine missiles leave the shoulders in turn.
5. Descend: he drifts back down to his normal stance.

The missiles arc up, dive on the enemy line and each one explodes.

## Sheet 1: hero poses (save as `generated/poses.png`)

Background: flat light grey `#C8C8C8`, nothing else, no ground, no shadow.
Layout: one row of exactly 5 poses, left to right in the storyboard order, each pose fully inside its own fifth of the image, never touching its neighbor.

```
Use the attached character (ref_01 and the armor parts sheet) and keep his design exactly: the crimson and navy armor with white trim, the cyan glowing chest reactor, the helmet with two antennas, the chibi game proportions (big head, small body).
Draw 5 separate full-body key poses of this same character for a 2D mobile game skill animation, in one image, in a single row, left to right:
1. CROUCH: knees bent, torso leaning forward, fists clenched at his sides, shoulder pods closed, gathering energy.
2. RISE: shooting straight up, body stretched long, legs together pointing down, arms along the body, head up. Do not draw flames or exhaust.
3. HOVER AND CHARGE: floating, arms spread wide open to the sides with palms out, chest reactor glowing bright, the two shoulder missile pods flipped open and visible.
4. FIRE: same floating position, torso leaning back from recoil, both arms thrown forward and slightly up, shoulder pods open and puffing smoke.
5. DESCEND: drifting downward, arms relaxed and slightly out, one leg a little forward, close to a neutral stance.
Same camera for all five: the same three-quarter view and the same scale as the reference, the character facing right.
Flat light grey background #C8C8C8 only. No ground, no cast shadow, no motion lines, no flames, no text, no frames, no watermark.
Each pose fully inside its own fifth of the image with clear empty space between poses.
Clean 2D game illustration, crisp dark outline, cel shading with strong highlights, high contrast so it reads at small size on a phone.
```

## Sheet 2: explosion frames (save as `generated/explosion.png`)

Background: pure black `#000000`. The effect is keyed from the black, so there is no background to remove.
Layout: a grid of 3 columns x 2 rows, 6 frames of one explosion in time order, row by row, left to right.

```
Draw one ground explosion for a 2D mobile game as 6 animation frames on a pure black background, in a grid of 3 columns by 2 rows, in time order row by row:
1. a small bright white-gold flash at ground level
2. a fireball expanding
3. the peak: a big orange and yellow fireball with a flat shock ring on the ground
4. the fireball breaking up, dark smoke starting to rise
5. rising smoke with glowing embers
6. thin fading smoke and a few embers
Side view, the ground is at the bottom of each cell and the explosion sits on it. Same scale and same style in every frame, painterly fire with bright cores, hot orange and yellow with a touch of cyan-white in the hottest core.
Pure black #000000 background, nothing else, no ground texture, no text, no grid lines, no watermark. Each frame fully inside its own cell, not touching the cell edges.
```

## Sheet 3: missile and launch smoke (save as `generated/missile.png`)

Background: pure black `#000000`.
Layout: top row: 1 missile, wide. Bottom row: 3 launch puffs, in time order.

```
On a pure black background draw, for a 2D mobile game:
Top row, one image: a slim cruise missile seen from the side pointing to the RIGHT, crimson body with a white band and small dark fins, a glowing cyan-white nose tip, and a long bright orange-white exhaust flame and smoke trail streaming to the LEFT behind it. Straight horizontal, ready to be rotated in the game.
Bottom row, 3 separate images in time order: a launch puff from a shoulder missile pod: (1) a bright muzzle flash, (2) the flash fading with a puff of grey smoke, (3) a thin drifting smoke wisp.
Pure black #000000 background, nothing else, no text, no watermark, everything fully inside its own area with space around it.
```

## Tips

- Generate each sheet 2 to 4 times and keep the best; the poses must look like the same character as `ref_01`.
- If the AI merges or crops poses, ask again: "Five separate poses in one row, each fully inside its own fifth of the image, with empty space between them."
- Resolution: anything around 1400 px wide or more is plenty.
- If the AI draws the missile or fire with a grey background instead of black, ask again for pure black `#000000`.

## What Claude does next

Cuts the poses out of the grey, keys the effects from the black, packs them into the Iron Man atlas, then builds the animation: moves between the poses with squash and stretch, the missiles arcing with their trails, one explosion per target, a screen shake on the heavy hit, all on the hit timing the battle already uses.
