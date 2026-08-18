# Tu Primera Optimización con MutaLambda

## 1. Analiza tu código
```bash
mutalambda recommend my_script.py
# → analiza imports y tamaño → sugiere preset + config
```

## 2. Genera la configuración
```bash
mutalambda init
# Wizard interactivo: tipo de código + agresividad → config.yaml
```

## 3. Optimiza
```bash
# Opción A: con un archivo
mutalambda production my_script.py

# Opción B: con config explícita
mutalambda evolve --config config.yaml --source my_script.py --tests my_tests.json
```

## 4. Monitorea
```bash
mutalambda dashboard --text          # resumen de runs anteriores
mutalambda doctor my_script.py       # diagnosticar configuración
```

## 5. Interpreta resultados
```bash
mutalambda explain-run checkpoints/run_<id>
# → score mejor, historia de fitness, % mejora
```
