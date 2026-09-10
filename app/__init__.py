"""POE — Personal Observation Engine.

`__version__` e' la fonte della versione a RUNTIME: il Dockerfile non copia
pyproject.toml nell'immagine, quindi leggerla da li' romperebbe in container.
tests/test_requirements_sync.py verifica che i due valori coincidano.
"""

__version__ = "0.8.0"
