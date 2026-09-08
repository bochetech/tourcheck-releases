"""Configuración de proveedores y modelos, por rol.

No hay "un modelo": hay **roles** con exigencias distintas y precios muy
distintos. El tutor tiene que sostener la disciplina socrática cuando el niño
insiste en que le den la respuesta; el chequeo de anclaje corre en cada turno y
debe costar casi nada; la extracción del currículo va por lotes y sin ningún niño
delante. Mezclarlos en un único ajuste obliga a pagar el modelo caro para todo o
a degradar lo que no se puede degradar.

La separación además no es solo de costo: los términos de uso de los proveedores
difieren respecto de menores, y este módulo lo hace explícito
(`Proveedor.apto_para_menores`) en vez de dejarlo en una nota del diseño.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

RUTA_CONFIG_POR_DEFECTO = Path(__file__).resolve().parents[2] / "config" / "modelos.yaml"


class Rol(str, Enum):
    """Cada tarea del sistema que necesita un modelo."""

    TUTOR = "tutor"
    ANCLAJE = "anclaje"
    RUBRICA = "rubrica"
    EXTRACCION = "extraccion"
    ENRIQUECIMIENTO = "enriquecimiento"
    ITEMS = "items"
    RESUMEN = "resumen"


#: Roles que procesan lo que dice un niño, en vivo. Los términos de uso del
#: proveedor importan aquí; en el resto, no hay menor de por medio.
ROLES_CARA_AL_NINO: frozenset[Rol] = frozenset({Rol.TUTOR, Rol.ANCLAJE, Rol.RUBRICA})


class Proveedor(BaseModel):
    """Un endpoint compatible con la API de OpenAI.

    Ollama y LM Studio exponen esa misma interfaz, así que pasar de local a nube
    es cambiar `base_url` y la clave — no reescribir el cliente.
    """

    id: str
    base_url: str
    api_key_env: str = "OPENAI_API_KEY"
    apto_para_menores: bool = False
    notas: str = ""

    def api_key(self) -> str | None:
        return os.environ.get(self.api_key_env)


class ModeloConfig(BaseModel):
    """Qué modelo usa un rol, y con qué límites."""

    proveedor: str
    modelo: str
    temperatura: float = 0.2
    max_tokens: int = 1024
    #: Tope de contexto recuperado por turno. Por encima de ~1500 tokens un
    #: modelo local de 7-12B empieza a degradarse notablemente.
    presupuesto_contexto: int | None = None


class Aviso(BaseModel):
    """Un problema de configuración, con su consecuencia explicada."""

    rol: Rol | None
    mensaje: str
    grave: bool = False

    def __str__(self) -> str:  # pragma: no cover - conveniencia
        marca = "ERROR" if self.grave else "aviso"
        donde = f" [{self.rol.value}]" if self.rol else ""
        return f"{marca}{donde}: {self.mensaje}"


class Config(BaseModel):
    """Configuración efectiva: qué proveedor y modelo usa cada rol."""

    perfil: str = "local"
    proveedores: dict[str, Proveedor] = Field(default_factory=dict)
    roles: dict[Rol, ModeloConfig] = Field(default_factory=dict)

    # ---- consulta ------------------------------------------------------------

    def para(self, rol: Rol) -> ModeloConfig:
        """Devuelve la configuración de un rol, o falla diciendo cuál falta."""
        if rol not in self.roles:
            raise KeyError(f"no hay modelo configurado para el rol '{rol.value}'")
        return self.roles[rol]

    def proveedor_de(self, rol: Rol) -> Proveedor:
        cfg = self.para(rol)
        if cfg.proveedor not in self.proveedores:
            raise KeyError(
                f"el rol '{rol.value}' apunta al proveedor '{cfg.proveedor}', "
                "que no está declarado"
            )
        return self.proveedores[cfg.proveedor]

    # ---- verificación --------------------------------------------------------

    def revisar(self) -> list[Aviso]:
        """Comprueba la coherencia de la configuración antes de gastar dinero.

        Detecta tres cosas que duelen tarde: roles sin modelo, claves de API
        ausentes, y —la importante— un rol que procesa a un menor en vivo
        apuntando a un proveedor cuyos términos no lo permiten.
        """
        avisos: list[Aviso] = []

        for rol in Rol:
            if rol not in self.roles:
                avisos.append(
                    Aviso(rol=rol, grave=True, mensaje="no tiene modelo configurado")
                )
                continue

            cfg = self.roles[rol]
            prov = self.proveedores.get(cfg.proveedor)
            if prov is None:
                avisos.append(
                    Aviso(
                        rol=rol,
                        grave=True,
                        mensaje=f"apunta al proveedor '{cfg.proveedor}', no declarado",
                    )
                )
                continue

            if rol in ROLES_CARA_AL_NINO and not prov.apto_para_menores:
                avisos.append(
                    Aviso(
                        rol=rol,
                        grave=True,
                        mensaje=(
                            f"procesa lo que dice un niño en vivo, pero el proveedor "
                            f"'{prov.id}' no está marcado como apto para menores. "
                            f"{prov.notas}".strip()
                        ),
                    )
                )

            if prov.base_url.startswith("https://") and prov.api_key() is None:
                avisos.append(
                    Aviso(
                        rol=rol,
                        mensaje=f"falta {prov.api_key_env} para '{prov.id}'",
                    )
                )

        return avisos


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------


def _aplicar_env(config: Config) -> Config:
    """Deja que el entorno pise la configuración, rol por rol.

    `AULA_MODELO_TUTOR=gpt-5-mini` cambia solo el tutor; `AULA_PROVEEDOR_TUTOR`
    cambia su proveedor. Es lo que permite comparar local contra nube sin tocar
    archivos ni reiniciar nada más.
    """
    for rol in Rol:
        sufijo = rol.value.upper()
        if (modelo := os.environ.get(f"AULA_MODELO_{sufijo}")) and rol in config.roles:
            config.roles[rol].modelo = modelo
        if (prov := os.environ.get(f"AULA_PROVEEDOR_{sufijo}")) and rol in config.roles:
            config.roles[rol].proveedor = prov

    if presupuesto := os.environ.get("AULA_MAX_TOKENS_RAG"):
        for cfg in config.roles.values():
            if cfg.presupuesto_contexto is not None:
                cfg.presupuesto_contexto = int(presupuesto)

    return config


def cargar_config(
    ruta: str | Path | None = None, perfil: str | None = None
) -> Config:
    """Carga la configuración de modelos desde YAML y aplica el entorno.

    El perfil sale, por orden de prioridad: del argumento, de `AULA_PERFIL`, o
    del `perfil_por_defecto` del archivo.
    """
    ruta = Path(ruta) if ruta else RUTA_CONFIG_POR_DEFECTO
    with Path(ruta).open(encoding="utf-8") as fh:
        datos = yaml.safe_load(fh) or {}

    proveedores = {
        pid: Proveedor(id=pid, **cuerpo)
        for pid, cuerpo in (datos.get("proveedores") or {}).items()
    }

    perfiles = datos.get("perfiles") or {}
    elegido = perfil or os.environ.get("AULA_PERFIL") or datos.get("perfil_por_defecto")
    if elegido not in perfiles:
        disponibles = ", ".join(sorted(perfiles)) or "ninguno"
        raise KeyError(f"perfil '{elegido}' no existe. Disponibles: {disponibles}")

    roles = {
        Rol(nombre): ModeloConfig(**cuerpo)
        for nombre, cuerpo in perfiles[elegido].items()
    }

    return _aplicar_env(Config(perfil=elegido, proveedores=proveedores, roles=roles))
