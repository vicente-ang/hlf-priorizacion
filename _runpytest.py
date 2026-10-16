import subprocess, sys
r = subprocess.run([sys.executable, "-m", "pytest", "-q"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
salida = r.stdout + "\n" + r.stderr
open("_pytest_full.txt", "w", encoding="utf-8").write(salida)
resumen = [l for l in salida.splitlines() if ("passed" in l.lower() or "failed" in l.lower() or l.startswith("FAILED"))]
print("RETURNCODE:", r.returncode)
print("\n".join(resumen[-5:]) if resumen else "(sin resumen)")
