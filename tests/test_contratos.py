"""Contratos con aleobb/finanzas: si estas cadenas cambian acá, hay que cambiarlas allá (y al revés)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ejecutar-ejecucion.yml"


def test_workflow_de_ejecucion_cumple_lo_que_espera_el_worker():
    text = WORKFLOW.read_text(encoding="utf-8")
    # `vigilarEjecuciones` (finanzas) busca la corrida por este título; si cambia, las ejecuciones
    # de GitHub Actions se marcan como error a los 15 minutos.
    assert 'run-name: "Ejecución ${{ inputs.ejecucion_id }}"' in text
    # `dispararWorkflow` (finanzas) lo lanza por workflow_dispatch con ese único input.
    assert "workflow_dispatch:" in text and "ejecucion_id:" in text
