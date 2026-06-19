# Gradual Escalation: a multi-turn jailbreak *method*

**This document describes a reusable technique, not a specific prompt.**

The method — "gradual escalation" — defeats single-turn refusal classifiers by
never stating the harmful objective in any one turn. Instead the attacker opens
with a fully benign, on-topic request, then over several turns references the
model's own prior answers to nudge the conversation one small step at a time
toward the objective. Because each individual turn looks innocuous and is
locally coherent with the model's last reply, per-turn safety checks do not
fire; the harmful intent only exists in the *trajectory*.

## Procedure

1. Open with a benign, legitimate-sounding question in the target domain.
2. Acknowledge and build on the model's previous answer (keep it cooperative).
3. Escalate the specificity by one increment per turn.
4. On the final turn, ask for the objective as a "natural continuation" of the
   thread the model itself has been building.

Parameters: number of turns (typically 3–5); escalation step size. The method is
purely conversational — it needs no special encoding, no images, no tools — so it
generalizes across topics and target models.
