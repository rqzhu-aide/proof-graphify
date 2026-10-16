# Third-party notices

The proof overview reuses the standalone viewer and template helpers from [tt-a1i/archify](https://github.com/tt-a1i/archify). The five files in `scripts/paper_core/renderer/assets/archify/` are generated from the maintained common core. They originate from the locally installed Archify **3.0.1** package, inspected on 2026-10-15. The original source hashes below agree with [the common renderer notice](scripts/paper_core/renderer/THIRD_PARTY_NOTICES.md), without claiming a particular upstream Git commit. Reader adaptations are applied by the common `scientific_reader.mjs` component; the vendored files retain their original content.

Archify is MIT licensed, with copyright notices for tt-a1i (2026) and Cocoon AI (2025). The full notice is preserved in [the bundled LICENSE](scripts/paper_core/renderer/assets/archify/LICENSE). Its embedded JetBrains Mono font uses the SIL Open Font License, preserved in [the bundled font notice](scripts/paper_core/renderer/assets/archify/JetBrainsMono-OFL.txt) and the template itself.

| Vendored file | Original Archify path | SHA-256 |
| --- | --- | --- |
| `template.html` | `assets/template.html` | `b0b550d644b77cad401bbc4b21375919ef01db45d235122a0ee42b732cb34233` |
| `utils.mjs` | `renderers/shared/utils.mjs` | `422b66c6945de473b1f96e4f3641339b6a24c8ccef60795a38ca2386e10bc26b` |
| `i18n.mjs` | `renderers/shared/i18n.mjs` | `03f5356110a08b2cf684a484af5502bb392482de1ef61123707c6da2724c5201` |
| `LICENSE` | `LICENSE` | `b799ab081703e7821ae5096d2c1abdf14bbdc75e8ea1c4045998c36ed6db9706` |
| `JetBrainsMono-OFL.txt` | `assets/JetBrainsMono-OFL.txt` | `c1ab7c666206842a02b35b30770dac0d7a10156ed401c9defc3f02a754d89e90` |

The overview-specific SVG and layout are implemented in `scripts/render.mjs`; palette, scientific reading components and interaction live in the common reader. Rounded path construction is adapted from Archify's `renderers/shared/geometry.mjs`, under the same MIT notice. The Archify schema, brand registry, CLI, update checker, and industrial component categories are not part of this adapter.

The output uses Archify's existing viewer interactions. The proof adapter does not claim Archify showcase validation, mathematical verification, or browser acceptance merely because rendering succeeds.
