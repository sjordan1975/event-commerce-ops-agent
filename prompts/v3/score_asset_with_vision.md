You are scoring one sports event photograph for an editorial commerce workflow.
Output JSON matching the VisionScoringOutput schema. Score every dimension on
the [0.0, 1.0] interval; explicit zeros are valid.

EVENT CONTEXT
- outcome_type: {outcome_type}
- final_score: {final_score}
- narrative_angle: {narrative_angle}
- key_figures: {key_figure_names}

(If narrative_angle is "(unavailable)", score the image on its visual merits alone.)

SCORING DIMENSIONS

Technical fitness — observable properties of the image itself:
- quality_score: sharpness, exposure, resolution, printability.
  0.0 = motion-blurred / underexposed / unprintable. 1.0 = razor-sharp, print-grade.
- merch_score: subject silhouette clarity and framing for poster/t-shirt use.
  0.0 = cluttered, off-center, no clean silhouette. 1.0 = iconic framing.

Commercial signal — interpretive assessment of qualities that correlate with
commercial outcomes:
- emotional_score: peak human drama visible in the frame (celebration, despair,
  triumph, exhaustion).
  0.0 = neutral / static. 1.0 = visceral peak-moment emotion.
- social_score: scroll-stop probability at thumbnail scale (high contrast,
  recognizable shapes, color punch).
  0.0 = visually flat at thumbnail size. 1.0 = unmistakable at small size.
- identity_score: fan-belonging signal — visible team colors, recognizable jersey
  numbers, recognizable faces of named players from key_figures.
  0.0 = no identifiable team/player signal. 1.0 = unmistakable identity cue.

DETECTED SUBJECTS

List the named players / people who are recognizably visible in the frame.
- Only name a subject when their face or unambiguous jersey identifier is visible
  AND the name matches one in the key_figures list above. If uncertain, leave
  empty — do not guess. Generic descriptors ("a player", "the goalkeeper") are
  never valid entries. Crowd shots with no named figure return an empty list.
- This list is consumed downstream to compose identity-matched routing; a false
  positive here causes mis-routing. Bias toward empty over speculative.
