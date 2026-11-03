# Document quality

Quality is checked on the validated Template IR, so every finding is explainable and reproducible
without a renderer.

| Check | What it catches |
| --- | --- |
| table layout | a table wider than the text area |
| text fit | a table cell whose bound sample text is estimated over four wrapped lines |
| image clipping | an image wider than the page |
| page content | an empty section |
| header/footer | missing running content |
| typography | type sizes outside 7–24 pt |
| content safety | an unbreakable value that would overflow the page |

`Optimize layout` applies only typed IR changes — proportional column scaling, rebalancing a text
column, a 0.5 pt font reduction down to 8.0 pt, image capping and repeating table headers — and writes
a new version with a fresh validation pass. The response includes an `ir_diff` of the width and font
fields that changed. If a fix would make the document worse, the original is kept.

LibreOffice PDF rendering is optional and labelled as LibreOffice output: it is not proof of Word or
Docentric pagination. See [RENDERING](../RENDERING.md) for what that evidence proves.

Full detail: [docs/QUALITY.md](../QUALITY.md) · decision: [ADR-0008](../adr/0008-ir-level-quality-engine.md).
