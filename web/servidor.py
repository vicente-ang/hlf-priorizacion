"""Sirve el front (web/) y guarda las decisiones en salidas/registro_decisiones.csv. Solo biblioteca estándar.

Uso:
  python -m web.servidor                 # http://localhost:8000  (regenera web/datos.js antes de abrir)
  python -m web.servidor --puerto 8080 --sin-construir

Abrir web/index.html con doble clic también funciona; en ese caso las decisiones quedan solo en el navegador.
El registro es el mismo que usa la interfaz Streamlit (app.py), con las mismas columnas.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parent
CAMPOS = ["fecha_registro", "usuario", "rol", "fecha_lista", "especialidad", "id_paciente", "puesto_propuesto",
          "motivo_propuesto", "decision", "puesto_final", "motivo", "modo", "version_regla"]
DECISIONES_VALIDAS = {"ia_aceptada", "ia_rechazada", "prioridad_absoluta", "revertida", "adelantado"}


def registro() -> Path:
    return Path(os.environ.get("HLF_REGISTRO", RAIZ / "salidas" / "registro_decisiones.csv"))


def guardar(fila: dict) -> None:
    """Agrega una decisión al registro (crea el archivo con encabezado si no existe)."""
    if fila.get("decision") not in DECISIONES_VALIDAS or not fila.get("id_paciente"):
        raise ValueError("decisión inválida")
    destino = registro()
    destino.parent.mkdir(parents=True, exist_ok=True)
    nuevo = not destino.exists()
    with open(destino, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS, extrasaction="ignore")
        if nuevo:
            w.writeheader()
        w.writerow({k: str(fila.get(k, ""))[:500] for k in CAMPOS})


class Manejador(SimpleHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 (nombre que exige http.server)
        if self.path != "/api/decision":
            self.send_error(404)
            return
        try:
            largo = min(int(self.headers.get("Content-Length", 0)), 20_000)
            guardar(json.loads(self.rfile.read(largo) or b"{}"))
        except (ValueError, json.JSONDecodeError) as e:
            self.send_error(400, str(e))
            return
        self.send_response(204)
        self.end_headers()

    def log_message(self, formato, *args):  # silencioso salvo errores
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(formato, *args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--puerto", type=int, default=8000)
    ap.add_argument("--sin-construir", action="store_true", help="no regenerar web/datos.js")
    a = ap.parse_args()
    if not a.sin_construir or not (WEB / "datos.js").exists():
        sys.path.insert(0, str(RAIZ))
        from web.construir import construir
        d = construir()
        print(f"datos.js: {len(d['pacientes'])} pacientes, corte {d['meta']['corte']}")
    srv = ThreadingHTTPServer(("127.0.0.1", a.puerto), partial(Manejador, directory=str(WEB)))
    print(f"Abrir http://localhost:{a.puerto}  (Ctrl+C para salir). Decisiones -> {registro()}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
