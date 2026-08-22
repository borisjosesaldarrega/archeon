# ARCHEON — UI Polish + Ghost Radial 2.0

Fecha de validación: 2026-08-22.

## Comparación visual

| Vista | Antes | Después |
| --- | --- | --- |
| Interfaz completa | [Captura](before/full-ui.png) | [Captura](after/full-ui.png) |
| Configuración | [Captura](before/settings.png) | [Captura](after/settings.png) |
| Launcher | [Captura](before/launcher.png) | [Captura](after/launcher.png) |
| Ghost radial | No existía como un único canvas circular | [Vista de validación geométrica](after/ghost-radial.png) |

La imagen de Ghost radial es una vista de QA generada con la misma función de distribución, dimensiones y paleta del canvas nativo. Windows Graphics Capture no expone de forma fiable esta ventana Tk transparente sin marco; el comportamiento real también se verificó ejecutando `--ghost --benchmark-radial`.

## Cambios verificados

- Input integrado en una sola barra con acción circular.
- Reproductor dentro del flujo del layout; aparece únicamente con música activa y no cubre el input.
- Orbe y anillos diferenciados por estado. La animación en reposo respeta `idle_animation=false` para no mantener activo el compositor.
- Configuración y Launcher contenidos dentro del viewport con scroll interno.
- Ghost radial compuesto en un solo proceso y un solo canvas nativo, con acciones contextuales, tooltips y expansión/contracción breve.
- El radial se desplaza temporalmente hacia el área visible si el orbe está junto a un borde y restaura su posición exacta al cerrarse.
- Video de fondo en ECO carga una imagen inicial y pausa la decodificación continua.

## Layout responsive

El probe real de WebView validó 7 tamaños lógicos: compacto, 1280×720, 1366×768, 1600×900, 1707×960, 1920×1080 y 2560×1440. En todos pasaron estas condiciones:

- input, reproductor, estado y orbe dentro del viewport;
- sin solapamientos verticales entre esos cuatro bloques;
- Configuración y Launcher dentro del viewport.

Resultados detallados: [`benchmarks/ui-layout.json`](../../benchmarks/ui-layout.json).

## Benchmark final

| Escenario | Inicio Core | RAM promedio | CPU promedio | GPU | Procesos |
| --- | ---: | ---: | ---: | ---: | ---: |
| Core headless | 12.314 ms | 30.602 MB | 0.00% | 0.00% | 1 |
| Full UI | 10.894 ms | 498.654 MB | 1.79% | 0.00% | 7 |
| Ghost | 11.275 ms | 44.867 MB | 0.00% | 0.00% | 1 |
| Ghost radial | 13.627 ms | 45.672 MB | 0.00% | 0.00% | 1 |

El radial abierto agrega aproximadamente 0.8 MB respecto a Ghost cerrado, sin proceso adicional. Durante la implementación se detectó una regresión provisional de 19.25% CPU / 2.32% GPU en Full UI; se corrigió antes de cerrar la entrega respetando la opción de animación en reposo.

Resultados detallados: [`benchmarks/latest.json`](../../benchmarks/latest.json).
