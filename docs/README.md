---
id: PRV-00
titulo: Índice de la documentación de providers
estado: vigente
ultima_revision: 2026-11-21
resumen: Índice de los cinco documentos de providers (técnico, portales, operaciones, decisiones, pendientes) y reglas para mantenerlos sin duplicar información.
fuentes: [repo providers]
relacionados: [PRV-TEC, PRV-POR, PRV-OPS, PRV-DEC, PRV-PEN]
---

# Documentación de providers

Este repo tiene su **propia fuente documental, independiente** del repo `aleobb/finanzas` (aunque algún dato se repita). Describe solo la versión productiva actual. Si sos una IA, leé primero `AGENTS.md` (raíz).

| Documento | Para qué | Cuándo leerlo |
|---|---|---|
| [TECNICO.md](TECNICO.md) | Arquitectura, contrato Provider, CLI, credenciales, ejecuciones y agente, sincronización, extractor, navegador, pruebas, troubleshooting | Programar o depurar |
| [PORTALES.md](PORTALES.md) | Notas de cada portal y cómo agregar uno | Tocar un portal o sumar otro |
| [OPERACIONES.md](OPERACIONES.md) | VM Oracle, KasmVNC, túnel, comandos aprobados, workflows, ejecuciones fallidas, rotación de claves | Operar la VM o el agente |
| [DECISIONES.md](DECISIONES.md) | Decisiones vigentes, descartes y riesgos aceptados | Saber por qué es así |
| [PENDIENTES.md](PENDIENTES.md) | Backlog y datos por verificar | Saber qué falta |

## Reglas
1. Cada dato vive en **un solo documento** de este repo; los demás lo enlazan.
2. Frontmatter obligatorio (con `resumen`) y un **TL;DR** al inicio de cada sección.
3. Lo histórico se consulta en Git; aquí no se acumula.
4. `⚠` marca lo no verificado; nunca se documentan valores de secretos (lo valida `tools/docs_check.py` en CI).
