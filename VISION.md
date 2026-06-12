# DreamGen Vision

DreamGen exists to explore what is inside local image generation models: what
they imagine easily, where they fail, what styles and symbols they carry, and
how their boundaries shift when prompts, seeds, LoRAs, enhancers, and backends
change.

Treat DreamGen as an instrument for probing models, not just a button that makes
nice pictures.

It is also a perpetual local dream machine: a workstation-scale system that can
keep generating, recording, comparing, and reviewing model behavior over long
runs without depending on hosted generation services. Always-on operation is
valuable only when it preserves evidence, operator control, and clear boundaries
between private experiments and deliberate publication.

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

The UI, CLI, API, gallery, and metadata should make model exploration easier by
surfacing:

- active backend and model identity
- prompt, meta-prompt, seed, dimensions, steps, guidance, and enhancer state
- LoRA and plugin influence
- generation time and relevant backend metadata
- publication state separate from experiment state

Do not hide fallback, mock, or smoke behavior behind successful-looking output.
Diagnostic images are useful only when they are clearly labeled as diagnostic.

Because DreamGen may run perpetually, local deploy and testing workflows should
make the currently edited worktree visible quickly. Prefer mounted Docker
hot-reload for daily development, and full Docker rebuilds only when validating
production-image parity. A running local UI is not proof that the latest code is
deployed; verify the API shape and frontend health before handing work back.

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
- local hot-reload and mounted-container workflows that keep the dream machine
  running while making current code reviewable
- small backend improvements that preserve comparability across models

## Keep Out

Avoid work that turns DreamGen into a generic hosted image SaaS, a marketing
site, or a grab bag of unrelated automation.

Be skeptical of:

- cloud-first generation paths
- features that make experiments less reproducible
- backend additions with no clear way to inspect their behavior
- UI that hides model settings in favor of a simplified magic button
- publication flows that blur private exploration and public gallery output
- broad rewrites that do not improve model probing, comparison, or artifact
  traceability

## North Star

A user should be able to ask, "What is this model's imagination made of, and
where does it stop?" DreamGen should help them find out, save the evidence, and
compare the answer across models.
