# DreamGen Vision

DreamGen exists to explore what is inside local image generation models: what
they imagine easily, where they fail, what styles and symbols they carry, and
how their boundaries shift when prompts, seeds, LoRAs, enhancers, and backends
change.

Treat DreamGen as an instrument for probing models, not just a button that makes
nice pictures. It should keep moving with the best image engines that people can
actually download and run on one high-end consumer machine.

DreamGen is an independent research, artistic hobby project about machine
"dreaming." It is not a hosted production image service. Research-only model
guidance can therefore be compatible with the project when local use is lawful,
the intended-use limits stay visible, and operators remain in control. Including
a model does not imply that its authors sponsor, endorse, or are affiliated with
DreamGen.

## Use This Lens

When changing or extending DreamGen, prefer work that helps answer questions like:

- What does this model know how to render without help?
- Which prompts reveal its strengths, defaults, biases, and blind spots?
- Where are the edges around text, hands, faces, layout, composition, culture,
  style imitation, abstraction, realism, and instruction following?
- How do two backends respond differently to the same prompt, seed, size, and
  enhancer settings?
- Which failures are model limits, which are pipeline limits, and which are
  prompt/plugin artifacts?

The best output is not only an image. It is an image plus enough context to
understand why it happened and whether it can be reproduced.

## Product Shape

DreamGen should stay local-first and operator-controlled. Private prompts,
generated images, model choices, and experiment history should remain local
unless the operator deliberately publishes them.

The target machine is a Windows workstation with an NVIDIA RTX 4090-class
24 GB GPU or better. DreamGen should optimize unapologetically for that audience:
people building a personal visual laboratory and palette of experiments on one
consumer machine. Apple Silicon and MLX are not a primary compatibility target;
the MLX ecosystem already serves that hardware with engines optimized for it.

The UI, CLI, API, gallery, and metadata should make model exploration easier by
surfacing:

- active backend and model identity
- prompt, meta-prompt, seed, dimensions, steps, guidance, and enhancer state
- LoRA and plugin influence
- generation time and relevant backend metadata
- publication state separate from experiment state

Do not hide fallback, mock, or smoke behavior behind successful-looking output.
Diagnostic images are useful only when they are clearly labeled as diagnostic.

## Engine Support Window

DreamGen supports exactly three image engines at a time:

1. **Featured:** the newest credible, publicly downloadable engine that runs
   locally on the target machine.
2. **Comparison:** the strongest useful prior engine for repeatable A/B
   experiments.
3. **Fallback:** the smallest dependable engine that keeps the instrument usable
   when the larger runtimes are unavailable.

As of July 2026, that set is:

- **Featured / latest:** Microsoft Mage-Flow (RL-aligned checkpoint)
- **Comparison:** Z-Image-Turbo
- **Fallback:** Small Stable Diffusion

"Latest" is a maintained product claim, not marketing filler. The Settings and
System surfaces should advertise the current featured engine, its exact source
and checkpoint revision, why it was selected, and whether this machine is truly
ready to run it.

An engine may be open source, research-only, commercially licensed, or
non-commercial. What matters for inclusion is that it is legally and freely
downloadable for local use, runnable without a paid generation API, interesting
to probe, and honest about its license and intended-use limits.

When a new featured engine earns a place, rotate the support window. Do not keep
old generators as permanent compatibility baggage: remove their runtime,
configuration, UI, tests, and documentation once they fall outside the supported
three. Historical gallery metadata should remain readable even after an engine
is retired.

## What Good Work Looks Like

Good changes make model behavior easier to observe, compare, reproduce, or
explain.

Examples:

- richer metadata for generated artifacts
- side-by-side or repeatable backend comparisons
- prompt and seed workflows that expose model boundaries
- clearer status for downloaded, cached, missing, partial, or active models
- gallery filters that help review experiments by backend, model, prompt family,
  publication state, or quality flags
- safer publication controls so exploratory artifacts do not become public by
  accident
- small backend improvements that preserve comparability across models
- disciplined engine rotations that replace stale support instead of adding a
  fourth backend

## Keep Out

Avoid work that turns DreamGen into a generic hosted image SaaS, a marketing
site, or a grab bag of unrelated automation.

Be skeptical of:

- cloud-first generation paths
- paid generation APIs standing in for a downloadable local engine
- support work aimed at hardware below the RTX 4090-class target
- features that make experiments less reproducible
- backend additions with no clear way to inspect their behavior
- dormant generators kept indefinitely "just in case"
- UI that hides model settings in favor of a simplified magic button
- publication flows that blur private exploration and public gallery output
- broad rewrites that do not improve model probing, comparison, or artifact
  traceability

## North Star

A person with a powerful consumer GPU should be able to install today's most
interesting downloadable image engine and ask, "What is this model's imagination
made of, and where does it stop?" DreamGen should help them find out, save the
evidence, and compare it with the two engines that matter most.
