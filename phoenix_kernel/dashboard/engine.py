# PHX-NOTE (varredura 2026-08-21 rodada 2, achado #4): scaffolding
# inacabado - `Engine` nem consegue ser instanciado hoje (`initialize()`
# é abstrato em IEngine e nunca foi implementado aqui). Confirmado via
# grep que nada em phoenix_kernel importa `dashboard` - não está
# conectado a nenhuma rota, então não expõe fabricação nenhuma pro
# usuário HOJE. Deixado como está de propósito, sem inventar uma
# implementação: se algum dia isso for conectado a uma rota real, IEngine
# precisa ganhar um `initialize()` de verdade primeiro.
from .interfaces import IEngine

class Engine(IEngine):
    pass
