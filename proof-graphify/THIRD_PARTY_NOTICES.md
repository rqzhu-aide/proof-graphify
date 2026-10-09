# Third-party notices

The proof overview reuses the standalone viewer and template helpers from [tt-a1i/archify](https://github.com/tt-a1i/archify). The five files in `scripts/paper_core/renderer/assets/archify/` are generated from the maintained common core. They originate from the locally installed Archify skill copied on 2026-09-12, version **2.17**, with template generator **2.17.0-dev.1**. The original source hashes below record that provenance, without claiming a particular upstream Git commit. Reader adaptations are applied by the common `scientific_reader.mjs` component; the vendored files retain their original content.

Archify is MIT licensed, with copyright notices for tt-a1i (2026) and Cocoon AI (2025). The full notice is preserved in [the bundled LICENSE](scripts/paper_core/renderer/assets/archify/LICENSE). Its embedded JetBrains Mono font uses the SIL Open Font License, preserved in [the bundled font notice](scripts/paper_core/renderer/assets/archify/JetBrainsMono-OFL.txt) and the template itself.

| Vendored file | Original Archify path | SHA-256 |
| --- | --- | --- |
| `template.html` | `assets/template.html` | `b3583470b9ec789418207963405252141c710b1b8a5c08a6cfd03156712f3f7d` |
| `utils.mjs` | `renderers/shared/utils.mjs` | `20124265300eb286db184a053561005cc32b6128dc1bc1b3f9520ffa8d43a241` |
| `i18n.mjs` | `renderers/shared/i18n.mjs` | `0d9e839c3e5346160b0028d07fcf78c86671189e0714ea069dc99913e859fcdb` |
| `LICENSE` | `LICENSE` | `b799ab081703e7821ae5096d2c1abdf14bbdc75e8ea1c4045998c36ed6db9706` |
| `JetBrainsMono-OFL.txt` | `assets/JetBrainsMono-OFL.txt` | `c1ab7c666206842a02b35b30770dac0d7a10156ed401c9defc3f02a754d89e90` |

The overview-specific SVG and layout are implemented in `scripts/render.mjs`; palette, scientific reading components and interaction live in the common reader. Rounded path construction is adapted from Archify's `renderers/shared/geometry.mjs`, under the same MIT notice. The Archify schema, brand registry, CLI, update checker, and industrial component categories are not part of this adapter.

The output uses Archify's existing viewer interactions. The proof adapter does not claim Archify showcase validation, mathematical verification, or browser acceptance merely because rendering succeeds.
