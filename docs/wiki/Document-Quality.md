# Document quality

Quality is checked on the validated Template IR, so every finding is explainable and reproducible
without a renderer.

| Check | What it catches |
| --- | --- |
| table layout | a table wider than the text area |
| image clipping | an image wider than the page |
| page content | an empty section |
| header/footer | missing running content |
| typography | type sizes outside 7–24 pt |
| content safety | an unbreakable value that would overflow the page |

`Optimize layout` applies only typed IR changes — proportional column scaling, image capping and
repeating table headers — and writes a new version with a fresh validation pass. If a fix would make
the document worse, the original is kept.

LibreOffice PDF rendering is optional and labelled as LibreOffice output: it is not proof of Word or
Docentric pagination.

Full detail: [docs/QUALITY.md](../QUALITY.md) · decision: [ADR-0008](../adr/0008-ir-level-quality-engine.md).
