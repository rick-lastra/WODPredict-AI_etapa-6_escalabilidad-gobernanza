"""
ejecutar_todo.py - Corre toda la evidencia de la Etapa 6 en orden.

    python -m src.ejecutar_todo            # completo (≈ 21 min, requiere Docker Desktop abierto)
    python -m src.ejecutar_todo --rapido   # solo el perfil de 0.5 vCPU en contenedores (≈ 6 min)
"""
import sys

from src import auditoria_fairness, bench_contenedores, bench_inferencia, costos, exportar_onnx, graficas

if __name__ == "__main__":
    rapido = "--rapido" in sys.argv
    print("\n=== 1/6 Exportar a ONNX y validar calidad ===")
    exportar_onnx.main()
    print("\n=== 2/6 Benchmark de inferencia en proceso ===")
    bench_inferencia.main()
    print("\n=== 3/6 Benchmark de contenedores (antes vs después) ===")
    sys.argv = [sys.argv[0]] + (["--rapido"] if rapido else [])
    bench_contenedores.main()
    print("\n=== 4/6 Estimación de costos ===")
    costos.main()
    print("\n=== 5/6 Auditoría de fairness ===")
    auditoria_fairness.main()
    print("\n=== 6/6 Gráficas ===")
    graficas.main()
