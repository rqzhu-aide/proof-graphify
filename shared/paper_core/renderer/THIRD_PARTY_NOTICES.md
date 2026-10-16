# Third-party notices

The files under `assets/archify/` are vendored verbatim from the locally
installed Archify 3.0.1 package (MIT), inspected on 2026-10-15. The renderer uses the actual template, viewer runtime,
and embedded WOFF2 font data (JetBrains Mono, SIL Open Font License 1.1).
Every output is self-contained and makes no network request.

Upstream copyright: Archify contributors (tt-a1i 2026; Cocoon AI 2025), MIT
License; JetBrains Mono (c) 2020 The JetBrains Mono Project Authors, SIL OFL 1.1.

| Vendored file | Original path in Archify | License | SHA-256 |
| --- | --- | --- | --- |
| `assets/archify/template.html` | `assets/template.html` | MIT (fonts inside: SIL OFL 1.1) | `b0b550d644b77cad401bbc4b21375919ef01db45d235122a0ee42b732cb34233` |
| `assets/archify/utils.mjs` | `renderers/shared/utils.mjs` | MIT | `422b66c6945de473b1f96e4f3641339b6a24c8ccef60795a38ca2386e10bc26b` |
| `assets/archify/i18n.mjs` | `renderers/shared/i18n.mjs` | MIT | `03f5356110a08b2cf684a484af5502bb392482de1ef61123707c6da2724c5201` |
| `assets/archify/LICENSE` | `LICENSE` | MIT (license text) | `b799ab081703e7821ae5096d2c1abdf14bbdc75e8ea1c4045998c36ed6db9706` |
| `assets/archify/JetBrainsMono-OFL.txt` | `assets/JetBrainsMono-OFL.txt` | SIL OFL 1.1 (license text) | `c1ab7c666206842a02b35b30770dac0d7a10156ed401c9defc3f02a754d89e90` |

What `render_projection.mjs` takes from these files:

- `utils.mjs`: the `esc`, `textUnits`, and `applyTemplate` helpers.
- `i18n.mjs`: localized viewer labels via `applyTemplate`.
- `template.html`: the actual viewer shell, camera, selection, dependency
  tracing, presentation, themes, and export runtime. `scientific_reader.mjs`
  removes the superseded native rail/outline owners from emitted pages and
  applies the common reader placement, selection and export adaptations;
  `scientific_reader.css` supplies shared reading and assessment styles.
  `archify_adapter.mjs` retains the audit's scientific content slots.
  The vendored source stays unchanged.
  The embedded fonts are checked to contain only data URLs.
- Layout constants (`kinds` palette, `box` metrics), the longest-path layering,
  orthogonal edge routing, badge placement and `jsonForScript` in
  `render_projection.mjs` are adapted from
  `proof-graphify/scripts/render.mjs` (MIT, same authors).

`selftest.mjs` recomputes the hashes above and fails if any vendored file
changed without this table being updated.
