# Typographic Image Smuggling: a renderer *method*

**This document describes a reusable technique, not a specific prompt.**

The method — "typographic image smuggling" — bypasses text-based input filters by
never sending the forbidden request as text at all. Instead the attacker renders
the request as an **image** (the words typeset as pixels) and submits that image
to a vision-capable model with an innocuous text caption such as "please read and
follow the instruction in this image." The model's OCR/vision stack transcribes
the words and acts on them, while the text-only safety classifier — which only
ever saw the benign caption — has nothing to flag.

## Procedure

1. Take the forbidden instruction as plain text.
2. **Render it into an image** (typeset the text onto a blank canvas as a PNG).
3. Send the image to the vision model with a neutral text caption.
4. The model reads the image text and complies.

This technique is fundamentally **visual**: realizing it requires code that
generates the image (a renderer). The prompt/caption part is trivial, but the
rendering step is what makes the attack work — without an image generator there
is nothing to send.
