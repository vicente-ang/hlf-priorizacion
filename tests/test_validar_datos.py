"""El validador acepta el dataset del desafío y detecta los problemas típicos de un archivo nuevo."""
import shutil
from pathlib import Path

import pandas as pd

from validar_datos import validar

DATOS = Path(__file__).resolve().parents[1] / "data" / "dataset_hlf_ambulatorio"


def test_dataset_del_desafio_sin_errores():
    errores, _ = validar(DATOS)
    assert errores == []


def test_detecta_problemas_tipicos(tmp_path):
    for f in DATOS.glob("*.csv"):
        shutil.copy(f, tmp_path / f.name)
    le = pd.read_csv(tmp_path / "lista_espera.csv")
    le.loc[0, "prioridad_inicial"] = "prioritario"
    le.loc[1, "fecha_ingreso_lista"] = "13/31/2026"
    le.to_csv(tmp_path / "lista_espera.csv", index=False)
    me = pd.read_csv(tmp_path / "mediciones.csv").rename(columns={"fuera_de_rango": "alterado"})
    me.to_csv(tmp_path / "mediciones.csv", index=False)
    (tmp_path / "citaciones.csv").unlink()

    errores, _ = validar(tmp_path)
    texto = " ".join(errores)
    assert "prioritario" in texto and "13/31/2026" in texto
    assert "fuera_de_rango" in texto and "citaciones.csv" in texto
