-- Wraps every header-row cell's content in \tableheadfont{...} (defined in
-- pdf_style.tex, Open Sans SemiBold) when producing LaTeX/PDF output.
--
-- Pandoc emits table header rows as plain text with no bold/weight markup
-- of its own, sandwiched between \toprule/\midrule (booktabs) — those rule
-- commands can't be hooked directly to inject a font switch without
-- breaking longtable's internal \noalign handling (confirmed empirically:
-- "Misplaced \noalign"). Operating on the Pandoc AST instead, before LaTeX
-- serialization, only ever touches header-cell text, never the surrounding
-- table structure.
function Table(tbl)
  if not FORMAT:match("latex") then
    return tbl
  end
  for _, cell in ipairs(tbl.head.rows[1].cells) do
    for _, block in ipairs(cell.contents) do
      if block.content then
        table.insert(block.content, 1, pandoc.RawInline("latex", "\\tableheadfont{"))
        table.insert(block.content, pandoc.RawInline("latex", "}"))
      end
    end
  end
  return tbl
end
