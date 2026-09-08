"""La configuración por rol debe impedir errores caros antes de gastar dinero."""

from __future__ import annotations

import pytest

from aula.config import (
    ROLES_CARA_AL_NINO,
    Config,
    ModeloConfig,
    Proveedor,
    Rol,
    cargar_config,
)


@pytest.fixture()
def config_local(monkeypatch):
    for var in list(dict(__import__("os").environ)):
        if var.startswith("AULA_"):
            monkeypatch.delenv(var, raising=False)
    return cargar_config(perfil="local")


def test_los_tres_perfiles_cargan_y_cubren_todos_los_roles():
    for perfil in ("local", "hibrido", "nube"):
        config = cargar_config(perfil=perfil)
        faltantes = set(Rol) - set(config.roles)
        assert not faltantes, f"perfil '{perfil}' no cubre {faltantes}"


def test_perfil_local_no_tiene_ningun_aviso(config_local):
    """Todo en el Mac: sin claves que falten y sin términos de terceros."""
    assert config_local.revisar() == []


def test_perfil_inexistente_dice_cuales_hay():
    with pytest.raises(KeyError, match="hibrido"):
        cargar_config(perfil="no-existe")


def test_avisa_si_un_rol_cara_al_nino_usa_un_proveedor_no_apto():
    """Es el chequeo que traduce los términos de uso en código, no en una nota."""
    config = Config(
        perfil="prueba",
        proveedores={
            "anthropic": Proveedor(
                id="anthropic",
                base_url="https://api.anthropic.com/v1",
                api_key_env="ANTHROPIC_API_KEY",
                apto_para_menores=False,
                notas="Sus términos exigen 18 años.",
            )
        },
        roles={rol: ModeloConfig(proveedor="anthropic", modelo="m") for rol in Rol},
    )

    avisos = config.revisar()
    roles_marcados = {a.rol for a in avisos if a.grave and a.rol in ROLES_CARA_AL_NINO}
    assert roles_marcados == set(ROLES_CARA_AL_NINO)
    assert any("18 años" in a.mensaje for a in avisos)


def test_los_roles_por_lotes_no_se_marcan_por_los_terminos():
    """Sin niño delante, los términos sobre menores no aplican."""
    config = Config(
        perfil="prueba",
        proveedores={
            "anthropic": Proveedor(
                id="anthropic",
                base_url="http://local",  # evita el aviso de clave ausente
                apto_para_menores=False,
            )
        },
        roles={
            Rol.EXTRACCION: ModeloConfig(proveedor="anthropic", modelo="m"),
            Rol.ITEMS: ModeloConfig(proveedor="anthropic", modelo="m"),
        },
    )

    graves = [a for a in config.revisar() if a.grave and a.rol in (Rol.EXTRACCION, Rol.ITEMS)]
    assert graves == []


def test_avisa_si_el_proveedor_no_esta_declarado():
    config = Config(
        perfil="prueba",
        proveedores={},
        roles={Rol.TUTOR: ModeloConfig(proveedor="fantasma", modelo="m")},
    )
    assert any("fantasma" in a.mensaje and a.grave for a in config.revisar())


def test_el_entorno_pisa_el_modelo_de_un_solo_rol(monkeypatch):
    """Comparar local contra nube no debe exigir editar archivos."""
    monkeypatch.setenv("AULA_MODELO_TUTOR", "gpt-5")
    monkeypatch.setenv("AULA_PROVEEDOR_TUTOR", "openai")

    config = cargar_config(perfil="local")

    assert config.para(Rol.TUTOR).modelo == "gpt-5"
    assert config.para(Rol.TUTOR).proveedor == "openai"
    # El resto del perfil queda intacto.
    assert config.para(Rol.ANCLAJE).proveedor == "ollama"


def test_el_entorno_pisa_el_presupuesto_de_contexto(monkeypatch):
    monkeypatch.setenv("AULA_MAX_TOKENS_RAG", "800")
    config = cargar_config(perfil="local")
    assert config.para(Rol.TUTOR).presupuesto_contexto == 800


def test_el_tutor_responde_corto_en_todos_los_perfiles():
    """Un tutor que escribe párrafos pierde al alumno: es una regla del método."""
    for perfil in ("local", "hibrido", "nube"):
        assert cargar_config(perfil=perfil).para(Rol.TUTOR).max_tokens <= 500


def test_el_anclaje_es_mas_barato_que_el_tutor():
    """Corre en cada turno; si cuesta como el tutor, duplica la factura."""
    for perfil in ("local", "hibrido", "nube"):
        config = cargar_config(perfil=perfil)
        assert config.para(Rol.ANCLAJE).max_tokens < config.para(Rol.TUTOR).max_tokens


def test_perfil_plan_premium_invierte_el_gasto_hacia_la_construccion():
    """Caro donde el error es permanente; barato donde es recuperable.

    Construir el plan pasa una vez por nivel y un prerrequisito mal inferido
    afecta a todas las sesiones futuras. Ejecutar clases pasa miles de veces y un
    turno flojo se corrige en el siguiente.
    """
    config = cargar_config(perfil="plan-premium")

    construccion = (Rol.EXTRACCION, Rol.ENRIQUECIMIENTO, Rol.ITEMS, Rol.RESUMEN)
    ejecucion = (Rol.TUTOR, Rol.ANCLAJE, Rol.RUBRICA)

    for rol in construccion:
        assert config.proveedor_de(rol).base_url.startswith("https://"), rol
    for rol in ejecucion:
        url = config.proveedor_de(rol).base_url
        assert url.startswith("http://") and "127.0.0.1" in url or "localhost" in url, rol


def test_plan_premium_no_dispara_avisos_por_menores():
    """Ningún niño interactúa con la API de pago en este perfil."""
    config = cargar_config(perfil="plan-premium")
    graves = [a for a in config.revisar() if a.grave]
    assert graves == []
