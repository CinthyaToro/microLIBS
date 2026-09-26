# -*- coding: utf-8 -*-
"""
tools/exportar_docx.py
======================
Convierte `docs/paper/manuscrito.md` en el .docx con el formato exacto que pide
la Guía para autores de LIBS-Spectra.

Lo que aplica, y que pandoc por sí solo no hace:

  · A4 (210 × 297 mm) con márgenes de 2,5 cm
  · Times New Roman 12 pt en todo el documento
  · numeración de página centrada al pie
  · **numeración de línea continua en el margen izquierdo**  ← el que más se olvida
  · las figuras insertadas en su lugar, a 16,6 cm de ancho

Correr después de completar cualquier hueco `[PENDIENTE]`, para mandarles a los
coautores la versión al día.

Requiere pandoc en el PATH.

Uso:
    python tools/exportar_docx.py
    python tools/exportar_docx.py --out docs/paper/Manuscript.docx
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import PROJECT_ROOT  # noqa: E402

FUENTE = PROJECT_ROOT / "docs" / "paper" / "manuscrito_v2.md"

# A4 y márgenes, en twips (1440 por pulgada)
SECTPR = (
    '<w:pgSz w:w="11906" w:h="16838"/>'
    '<w:pgMar w:top="1418" w:right="1418" w:bottom="1418" w:left="1418" '
    'w:header="709" w:footer="709" w:gutter="0"/>'
)

# La revista lo exige para el envío. Para circular entre coautores estorba,
# así que se puede desactivar con --sin-lineas.
NUM_LINEA = '<w:lnNumType w:countBy="1" w:restart="continuous" w:distance="284"/>'

def _rfonts(nombre: str) -> str:
    return ('<w:rFonts w:ascii="{n}" w:hAnsi="{n}" w:eastAsia="{n}" w:cs="{n}"/>'
            .format(n=nombre))


def _pie(fuente: str) -> str:
    f = _rfonts(fuente)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
            '<w:r><w:rPr>' + f + '<w:sz w:val="20"/></w:rPr>'
            '<w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:rPr>' + f + '<w:sz w:val="20"/></w:rPr>'
            '<w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
            '<w:r><w:rPr>' + f + '<w:sz w:val="20"/></w:rPr>'
            '<w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>')


def _preparar_markdown(md: str) -> str:
    """Adapta el Markdown a lo que pandoc entiende."""
    # <sup>x</sup> → ^x^  (superíndices de citas y filiaciones)
    md = re.sub(r"<sup>(.*?)</sup>",
                lambda m: "^" + m.group(1).replace(" ", r"\ ") + "^", md)

    # Los marcadores de figura pasan a ser la imagen real más su leyenda.
    def _figura(m):
        ruta, cuerpo = m.group(1), m.group(2)
        leyenda = "\n".join(l[2:] if l.startswith("> ") else l.lstrip(">")
                            for l in cuerpo.splitlines())
        leyenda = " ".join(x.strip() for x in leyenda.split("\n") if x.strip())
        return "![](%s){width=16.6cm}\n\n%s\n" % (ruta, leyenda)

    return re.sub(r"> \*\*\[FIGURA \d+ AQUÍ — `([^`]+)`\]\*\*\n>\n((?:>.*\n)+)",
                  _figura, md)


def _aplicar_formato(paquete: Path, numerar_lineas: bool = True,
                     fuente: str = "Times New Roman") -> None:
    """Parchea el .docx desempaquetado con el formato de la revista."""
    doc_p = paquete / "word" / "document.xml"
    doc = doc_p.read_text(encoding="utf-8")
    doc = re.sub(r"<w:pgSz[^/]*/>", "", doc)
    doc = re.sub(r"<w:pgMar[^/]*/>", "", doc)
    doc = re.sub(r"<w:lnNumType[^/]*/>", "", doc)
    doc = doc.replace(
        "<w:sectPr>",
        '<w:sectPr><w:footerReference w:type="default" r:id="rIdPie"/>'
        + SECTPR + (NUM_LINEA if numerar_lineas else ""))
    doc_p.write_text(doc, encoding="utf-8")

    # Fuente única: se quitan los overrides de pandoc y se fija en docDefaults.
    rf = _rfonts(fuente)
    st_p = paquete / "word" / "styles.xml"
    st = st_p.read_text(encoding="utf-8")
    st = re.sub(r"<w:rFonts[^/]*/>", "", st)
    st = re.sub(r"<w:szCs\s[^/]*/>", "", st)
    st = st.replace("<w:rPr>", "<w:rPr>" + rf, 1)
    if "<w:sz w:val=" in st:
        st = re.sub(r'<w:sz w:val="\d+"/>', '<w:sz w:val="24"/>', st, count=1)
    else:
        st = st.replace(rf, rf + '<w:sz w:val="24"/>', 1)
    st_p.write_text(st, encoding="utf-8")

    (paquete / "word" / "footerMS.xml").write_text(_pie(fuente), encoding="utf-8")

    rels_p = paquete / "word" / "_rels" / "document.xml.rels"
    rels_p.write_text(rels_p.read_text(encoding="utf-8").replace(
        "</Relationships>",
        '<Relationship Id="rIdPie" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/footer" Target="footerMS.xml"/>'
        "</Relationships>"), encoding="utf-8")

    ct_p = paquete / "[Content_Types].xml"
    ct_p.write_text(ct_p.read_text(encoding="utf-8").replace(
        "</Types>",
        '<Override PartName="/word/footerMS.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.wordprocessingml.footer+xml"/></Types>'),
        encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None,
                    help="ruta del .docx (por omisión, junto al manuscrito)")
    ap.add_argument("--sin-lineas", action="store_true",
                    help="sin numeración de línea al margen — para circular "
                         "entre coautores. El envío a la revista la necesita.")
    ap.add_argument("--fuente", default="Times New Roman",
                    help='fuente del cuerpo. La guía admite "una fuente '
                         'fácilmente legible (por ejemplo, Times New Roman o '
                         'Arial)", así que Arial es válido.')
    args = ap.parse_args()

    salida = Path(args.out) if args.out else (
        FUENTE.parent / "Manuscript_borrador.docx")

    if shutil.which("pandoc") is None:
        print("ERROR: hace falta pandoc en el PATH.", file=sys.stderr)
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="docx_"))
    try:
        md_tmp = tmp / "src.md"
        md_tmp.write_text(_preparar_markdown(FUENTE.read_text(encoding="utf-8")),
                          encoding="utf-8")

        crudo = tmp / "crudo.docx"
        subprocess.run([
            "pandoc", str(md_tmp), "-o", str(crudo),
            "--from", "markdown+pipe_tables+link_attributes",
            "--resource-path", str(FUENTE.parent),
            "--dpi=600",
        ], check=True)

        paquete = tmp / "paquete"
        with zipfile.ZipFile(crudo) as z:
            z.extractall(paquete)
        _aplicar_formato(paquete, numerar_lineas=not args.sin_lineas,
                         fuente=args.fuente)

        salida.parent.mkdir(parents=True, exist_ok=True)
        if salida.exists():
            salida.unlink()
        with zipfile.ZipFile(salida, "w", zipfile.ZIP_DEFLATED) as z:
            for base, _, files in os.walk(paquete):
                for f in files:
                    p = Path(base) / f
                    z.write(p, str(p.relative_to(paquete)).replace("\\", "/"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    pend = FUENTE.read_text(encoding="utf-8").count("PENDIENTE")
    print("%s  (%.0f kB)" % (salida.name, salida.stat().st_size / 1024))
    print("Fuente: %s 12 pt" % args.fuente)
    print("Numeración de línea: %s" % ("NO" if args.sin_lineas else "sí"))
    print("Huecos [PENDIENTE] que siguen abiertos: %d" % pend)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
