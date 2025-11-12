import json
import copy
from io import BytesIO
from typing import Dict, Any, List, Tuple, Optional

import pandas as pd
import streamlit as st
import xml.etree.ElementTree as ET
from xml.dom import minidom


# ==========================
# Constantes de campos
# ==========================

CAMPOS_PACIENTE = [
    "tipoDocumentoIdentificacion",
    "numDocumentoIdentificacion",
    "tipoUsuario",
    "fechaNacimiento",
    "codSexo",
    "codPaisResidencia",
    "codMunicipioResidencia",
    "codZonaTerritorialResidencia",
    "codPaisOrigen",
    "incapacidad",
    "consecutivo",
]

SERVICIO_GRUPOS = [
    "consultas",
    "procedimientos",
    "urgencias",
    "hospitalizacion",
    "recienNacidos",
    "medicamentos",
    "otrosServicios",
]

# Longitud fija para códigos (ceros a la izquierda)
CODIGOS_LONGITUD = {
    "tipoUsuario": 2,
    "codPaisResidencia": 3,
    "codPaisOrigen": 3,
    "codMunicipioResidencia": 5,
    "codZonaTerritorialResidencia": 2,
}


# ==========================
# Utilidades de negocio
# ==========================

def tiene_lista_con_items(servicios: Any) -> bool:
    """True si en 'servicios' hay al menos una lista con 1 ítem."""
    if not isinstance(servicios, dict):
        return False
    for v in servicios.values():
        if isinstance(v, list) and len(v) > 0:
            return True
    return False


def ajustar_signo_servicios(servicios: Dict[str, Any], signo: int) -> None:
    """Multiplica por 'signo' vrServicio y valorPagoModerador en todas las listas de servicios."""
    for lista in servicios.values():
        if not isinstance(lista, list):
            continue
        for item in lista:
            if not isinstance(item, dict):
                continue
            for campo in ("vrServicio", "valorPagoModerador"):
                if campo in item and isinstance(item[campo], (int, float)):
                    item[campo] = item[campo] * signo


def normalizar_servicios_usuario(usuario: Dict[str, Any]) -> None:
    """Asegura que existan todas las listas de servicios por usuario."""
    serv = usuario.get("servicios")
    if not isinstance(serv, dict):
        serv = {}
    for grupo in SERVICIO_GRUPOS:
        if not isinstance(serv.get(grupo), list):
            serv[grupo] = []
    usuario["servicios"] = serv


def normalizar_documento_servicios(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza la estructura de servicios en todos los usuarios del documento."""
    usuarios = doc.get("usuarios")
    if not isinstance(usuarios, list):
        return doc
    for u in usuarios:
        if isinstance(u, dict):
            normalizar_servicios_usuario(u)
    doc["usuarios"] = usuarios
    return doc


def formatear_codigo_campo(campo: str, valor: Any) -> str:
    """Aplica longitud fija y ceros a la izquierda según el campo."""
    if valor is None or valor == "":
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    s = str(valor)
    longitud = CODIGOS_LONGITUD.get(campo)
    if longitud:
        if s.isdigit() and len(s) <= longitud:
            s = s.zfill(longitud)
        elif len(s) < longitud:
            s = s.zfill(longitud)
    return s


def normalizar_codigos_usuarios(nota: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ajusta todos los usuarios:
      - tipoUsuario -> "08"
      - Códigos con ceros a la izquierda
      - fechaNacimiento en YYYY-MM-DD
      - consecutivo como int si es posible
    """
    usuarios = nota.get("usuarios", [])
    if not isinstance(usuarios, list):
        return nota

    for u in usuarios:
        if not isinstance(u, dict):
            continue

        # tipoUsuario fijo "08"
        u["tipoUsuario"] = "08"

        # Codificaciones de longitud fija
        for campo in ("codPaisResidencia", "codPaisOrigen",
                      "codMunicipioResidencia", "codZonaTerritorialResidencia"):
            if campo in u and u[campo] not in (None, ""):
                u[campo] = formatear_codigo_campo(campo, u[campo])

        # fechaNacimiento
        if "fechaNacimiento" in u and u["fechaNacimiento"]:
            u["fechaNacimiento"] = str(u["fechaNacimiento"])[:10]

        # consecutivo
        if "consecutivo" in u and u["consecutivo"] not in (None, ""):
            try:
                u[campo] = int(u["consecutivo"])
            except Exception:
                pass

    nota["usuarios"] = usuarios
    return nota


def copiar_servicios_factura_a_nota(
    factura: Dict[str, Any],
    nota: Dict[str, Any],
    forzar_signo: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Copia datos demográficos y servicios desde FACTURA -> NOTA.
    Empareja usuarios por tipoDocumento + numDocumento (y si no, por número).
    Solo copia servicios para usuarios que en la nota no tienen ninguna lista con ítems.
    """
    inv_users = factura.get("usuarios", [])
    note_users = nota.get("usuarios", [])

    inv_map_full: Dict[Tuple[str, str], Dict[str, Any]] = {}
    inv_map_by_num: Dict[str, Dict[str, Any]] = {}

    for u in inv_users:
        if not isinstance(u, dict):
            continue
        tipo = u.get("tipoDocumentoIdentificacion")
        num = u.get("numDocumentoIdentificacion")
        if not num:
            continue
        if tipo:
            inv_map_full[(tipo, num)] = u
        inv_map_by_num[num] = u

    usuarios_modificados = 0
    usuarios_ya_tenian_servicios = 0
    usuarios_demografia_completada = 0
    usuarios_sin_encontrar: List[Tuple[str, str]] = []

    for u in note_users:
        if not isinstance(u, dict):
            continue

        tipo = u.get("tipoDocumentoIdentificacion")
        num = u.get("numDocumentoIdentificacion")
        u_fact = inv_map_full.get((tipo, num)) or inv_map_by_num.get(num or "")

        if u_fact is None:
            usuarios_sin_encontrar.append((tipo, num))
            continue

        # Copiar SIEMPRE datos del paciente desde factura
        for campo in CAMPOS_PACIENTE:
            val = u_fact.get(campo, None)

            if campo == "tipoUsuario":
                u[campo] = "08"
                continue

            if val in (None, ""):
                continue

            if campo == "consecutivo":
                try:
                    u[campo] = int(val)
                except Exception:
                    u[campo] = val
            elif campo == "fechaNacimiento":
                u[campo] = str(val)[:10]
            elif campo in CODIGOS_LONGITUD:
                u[campo] = formatear_codigo_campo(campo, val)
            else:
                u[campo] = str(val)

        usuarios_demografia_completada += 1

        # Normalizar estructuras de servicios
        normalizar_servicios_usuario(u_fact)
        normalizar_servicios_usuario(u)

        if tiene_lista_con_items(u.get("servicios")):
            usuarios_ya_tenian_servicios += 1
            continue

        servicios_origen = u_fact.get("servicios", {})
        if not isinstance(servicios_origen, dict):
            continue

        nuevo_servicios = copy.deepcopy(servicios_origen)
        if forzar_signo in (1, -1):
            ajustar_signo_servicios(nuevo_servicios, forzar_signo)

        u["servicios"] = nuevo_servicios
        usuarios_modificados += 1

    nota["usuarios"] = note_users
    nota = normalizar_codigos_usuarios(nota)

    resumen = {
        "total_usuarios_factura": len(inv_users),
        "total_usuarios_nota": len(note_users),
        "usuarios_modificados": usuarios_modificados,
        "usuarios_ya_tenian_servicios": usuarios_ya_tenian_servicios,
        "usuarios_demografia_completada": usuarios_demografia_completada,
        "usuarios_sin_encontrar": usuarios_sin_encontrar,
    }
    return nota, resumen


def generar_resumen_usuarios(nota: Dict[str, Any]) -> pd.DataFrame:
    """Tabla resumen por usuario (estado de servicios)."""
    filas: List[Dict[str, Any]] = []
    for idx, u in enumerate(nota.get("usuarios", [])):
        servicios = u.get("servicios", {})
        tiene_serv = tiene_lista_con_items(servicios)
        num_listas = 0
        total_items = 0
        if isinstance(servicios, dict):
            for v in servicios.values():
                if isinstance(v, list):
                    num_listas += 1
                    total_items += len(v)
        filas.append(
            {
                "idx": idx,
                "tipoDocumentoIdentificacion": u.get("tipoDocumentoIdentificacion"),
                "numDocumentoIdentificacion": u.get("numDocumentoIdentificacion"),
                "estadoServicios": "OK" if tiene_serv else "INCOMPLETO",
                "numListasServicios": num_listas,
                "totalItemsServicios": total_items,
            }
        )
    return pd.DataFrame(filas)


def obtener_claves_servicio_esperadas(
    factura: Optional[Dict[str, Any]],
    nota: Optional[Dict[str, Any]],
) -> List[str]:
    """Toma el ítem de servicio más completo (con más campos) entre factura y nota y usa sus llaves como referencia."""
    mejor_keys: set = set()
    mejor_len = 0
    for doc in (factura, nota):
        if not doc:
            continue
        for u in doc.get("usuarios", []):
            servicios = u.get("servicios", {})
            if not isinstance(servicios, dict):
                continue
            for lista in servicios.values():
                if not isinstance(lista, list):
                    continue
                for item in lista:
                    if isinstance(item, dict):
                        ks = set(item.keys())
                        if len(ks) > mejor_len:
                            mejor_len = len(ks)
                            mejor_keys = ks
    return sorted(mejor_keys)


def desglosar_servicios_usuario(
    usuario: Optional[Dict[str, Any]],
    claves_esperadas: List[str],
) -> List[Dict[str, Any]]:
    """Devuelve una fila por servicio del usuario, indicando campos faltantes."""
    filas: List[Dict[str, Any]] = []
    if not usuario:
        return filas

    servicios = usuario.get("servicios") or {}
    if not isinstance(servicios, dict):
        return filas

    for tipo_servicio, lista in servicios.items():
        if not isinstance(lista, list):
            continue
        for idx_item, item in enumerate(lista):
            fila: Dict[str, Any] = {
                "tipo_servicio": tipo_servicio,
                "idx_item": idx_item,
            }
            faltantes: List[str] = []
            for clave in claves_esperadas:
                valor = item.get(clave) if isinstance(item, dict) else None
                fila[clave] = valor
                if valor in (None, ""):
                    faltantes.append(clave)
            fila["campos_faltantes"] = ",".join(faltantes)
            filas.append(fila)

    return filas


def generar_plantilla_servicios(
    nota: Dict[str, Any],
    factura: Optional[Dict[str, Any]],
) -> Tuple[BytesIO, str, str]:
    """
    Genera plantilla para edición masiva de servicios (demográficos + vrServicio).
    """
    claves_esperadas = obtener_claves_servicio_esperadas(factura, nota)
    filas: List[Dict[str, Any]] = []

    usuarios_nota = nota.get("usuarios", []) or []
    usuarios_fac = factura.get("usuarios", []) if factura else []

    for idx_u in range(len(usuarios_nota)):
        u_nota = usuarios_nota[idx_u]
        u_fac = usuarios_fac[idx_u] if 0 <= idx_u < len(usuarios_fac) else None

        filas_nota = desglosar_servicios_usuario(u_nota, claves_esperadas)
        filas_fac = desglosar_servicios_usuario(u_fac, claves_esperadas) if u_fac else []

        map_fac = {
            (f["tipo_servicio"], f["idx_item"]): f for f in filas_fac
        }

        def agregar_campos_paciente(base: Dict[str, Any]):
            for campo in CAMPOS_PACIENTE:
                if u_nota is not None and campo in u_nota:
                    base[campo] = u_nota.get(campo)
                elif u_fac is not None and campo in u_fac:
                    base[campo] = u_fac.get(campo)
                else:
                    base[campo] = None

        if filas_nota:
            for f in filas_nota:
                base_fac = map_fac.get((f["tipo_servicio"], f["idx_item"]), {})
                fila = {
                    "idx_usuario": idx_u,
                    "tipo_servicio": f["tipo_servicio"],
                    "idx_item": f["idx_item"],
                    "vrServicio_factura": base_fac.get("vrServicio"),
                    "vrServicio_nota": f.get("vrServicio"),
                    "campos_faltantes_nota": f.get("campos_faltantes", ""),
                }
                agregar_campos_paciente(fila)
                filas.append(fila)
        else:
            for f in filas_fac:
                fila = {
                    "idx_usuario": idx_u,
                    "tipo_servicio": f["tipo_servicio"],
                    "idx_item": f["idx_item"],
                    "vrServicio_factura": f.get("vrServicio"),
                    "vrServicio_nota": None,
                    "campos_faltantes_nota": "USUARIO SIN SERVICIOS EN NOTA",
                }
                agregar_campos_paciente(fila)
                filas.append(fila)

    df = pd.DataFrame(filas)
    buffer = BytesIO()
    ext = "xlsx"
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    try:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="servicios")
    except Exception:
        buffer = BytesIO()
        df.to_csv(buffer, index=False)
        ext = "csv"
        mime = "text/csv"

    buffer.seek(0)
    return buffer, ext, mime


def aplicar_plantilla_servicios(
    nota: Dict[str, Any],
    factura: Optional[Dict[str, Any]],
    archivo_plantilla,
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Aplica cambios de la plantilla:
      - Actualiza vrServicio_nota.
      - Puede actualizar también datos demográficos.
    """
    errores: List[str] = []

    try:
        nombre = getattr(archivo_plantilla, "name", "") or ""
        if nombre.lower().endswith(".csv"):
            df = pd.read_csv(archivo_plantilla)
        else:
            df = pd.read_excel(archivo_plantilla)
    except Exception as exc:
        errores.append(f"No se pudo leer la plantilla: {exc}")
        return nota, errores

    obligatorias = ["idx_usuario", "tipo_servicio", "idx_item", "vrServicio_nota"]
    for col in obligatorias:
        if col not in df.columns:
            errores.append(f"Falta columna obligatoria '{col}' en la plantilla.")
            return nota, errores

    usuarios_nota = nota.get("usuarios", [])
    usuarios_fac = factura.get("usuarios", []) if factura else []

    updated_indices = set(st.session_state.get("usuarios_actualizados_desde_excel", []))

    for _, fila in df.iterrows():
        try:
            idx_u = int(fila["idx_usuario"])
        except Exception:
            errores.append(f"Índice de usuario inválido: {fila.get('idx_usuario')}")
            continue

        tipo_serv = str(fila["tipo_servicio"])
        try:
            idx_item = int(fila["idx_item"])
        except Exception:
            errores.append(f"Índice de ítem inválido para usuario {idx_u}: {fila.get('idx_item')}")
            continue

        vr_nota = fila["vrServicio_nota"]
        if pd.isna(vr_nota):
            continue

        if not (0 <= idx_u < len(usuarios_nota)):
            errores.append(f"Índice de usuario {idx_u} fuera de rango.")
            continue

        usuario_nota = usuarios_nota[idx_u]

        # Actualizar datos del paciente si llegan en la plantilla
        for campo in CAMPOS_PACIENTE:
            if campo not in df.columns:
                continue
            valor = fila[campo]
            if pd.isna(valor):
                continue

            if campo == "tipoUsuario":
                usuario_nota[campo] = "08"
            elif campo == "consecutivo":
                try:
                    usuario_nota[campo] = int(valor)
                except Exception:
                    usuario_nota[campo] = valor
            elif campo == "fechaNacimiento":
                usuario_nota[campo] = str(valor)[:10]
            elif campo in CODIGOS_LONGITUD:
                usuario_nota[campo] = formatear_codigo_campo(campo, valor)
            else:
                if isinstance(valor, float) and valor.is_integer():
                    valor = int(valor)
                usuario_nota[campo] = str(valor)

        servicios_nota = usuario_nota.get("servicios")
        if not isinstance(servicios_nota, dict):
            servicios_nota = {}
            usuario_nota["servicios"] = servicios_nota

        lista = servicios_nota.get(tipo_serv)

        # Si la estructura no existe, intentar copiar desde factura
        if not (isinstance(lista, list) and idx_item < len(lista)):
            if not factura:
                errores.append(
                    f"No existe estructura para usuario {idx_u}, tipo '{tipo_serv}', "
                    f"ítem {idx_item} y no hay factura."
                )
                usuarios_nota[idx_u] = usuario_nota
                continue

            if 0 <= idx_u < len(usuarios_fac):
                usuario_fac = usuarios_fac[idx_u]
            else:
                errores.append(
                    f"No se encontró usuario {idx_u} en factura para crear estructura."
                )
                usuarios_nota[idx_u] = usuario_nota
                continue

            servicios_fac = usuario_fac.get("servicios", {})
            lista_fac = servicios_fac.get(tipo_serv)
            if not (isinstance(lista_fac, list) and idx_item < len(lista_fac)):
                errores.append(
                    f"No hay línea base en factura para usuario {idx_u}, "
                    f"tipo '{tipo_serv}', ítem {idx_item}."
                )
                usuarios_nota[idx_u] = usuario_nota
                continue

            item_base = copy.deepcopy(lista_fac[idx_item])
            if not isinstance(lista, list):
                lista = []
            while len(lista) <= idx_item:
                lista.append({})
            lista[idx_item] = item_base
            servicios_nota[tipo_serv] = lista

        lista = servicios_nota.get(tipo_serv, [])
        if not (isinstance(lista, list) and idx_item < len(lista)):
            errores.append(
                f"No se pudo asegurar la estructura para usuario {idx_u}, "
                f"tipo '{tipo_serv}', ítem {idx_item}."
            )
            usuarios_nota[idx_u] = usuario_nota
            continue

        item_nota = lista[idx_item]
        try:
            valor_nota = float(vr_nota)
        except Exception:
            errores.append(
                f"Valor vrServicio_nota inválido en usuario {idx_u}, "
                f"tipo '{tipo_serv}', ítem {idx_item}: {vr_nota}"
            )
            usuarios_nota[idx_u] = usuario_nota
            continue

        item_nota["vrServicio"] = valor_nota
        lista[idx_item] = item_nota
        servicios_nota[tipo_serv] = lista
        usuario_nota["servicios"] = servicios_nota
        usuarios_nota[idx_u] = usuario_nota
        updated_indices.add(idx_u)

    nota["usuarios"] = usuarios_nota
    nota = normalizar_codigos_usuarios(nota)
    st.session_state["usuarios_actualizados_desde_excel"] = sorted(list(updated_indices))
    return nota, errores


# ==========================
# XML interno RipsDocumento
# ==========================

def _add_generic_xml(parent: ET.Element, key: str, value: Any) -> None:
    """
    Conversión genérica dict -> XML:
      - dict  -> <key>...</key> con hijos
      - list  -> <key> repetido (o singular si termina en 's')
      - escalar -> <key>texto</key>
    """
    if isinstance(value, dict):
        elem = ET.SubElement(parent, key)
        for k, v in value.items():
            _add_generic_xml(elem, k, v)

    elif isinstance(value, list):
        child_tag = key[:-1] if key.endswith("s") else key
        for item in value:
            if isinstance(item, dict):
                elem = ET.SubElement(parent, child_tag)
                for k, v in item.items():
                    _add_generic_xml(elem, k, v)
            else:
                elem = ET.SubElement(parent, child_tag)
                elem.text = "" if item is None else str(item)

    else:
        elem = ET.SubElement(parent, key)
        elem.text = "" if value is None else str(value)


def nota_json_a_xml_element(nota: Dict[str, Any]) -> ET.Element:
    """
    Genera el XML interno RipsDocumento:
      - Recorre los campos estándar en orden:
        numDocumentoIdObligado, numFactura, informacionesAdicionales, tipoNota, numNota.
      - Luego añade otros campos top-level (si existen).
      - 'usuarios' se trata con estructura especial (usuario / servicios / items).
    """
    root = ET.Element("RipsDocumento")

    # Cabecera en orden típico
    if "numDocumentoIdObligado" in nota:
        _add_generic_xml(root, "numDocumentoIdObligado", nota["numDocumentoIdObligado"])
    if "numFactura" in nota:
        _add_generic_xml(root, "numFactura", nota["numFactura"])
    if "informacionesAdicionales" in nota:
        _add_generic_xml(root, "informacionesAdicionales", nota["informacionesAdicionales"])
    if "tipoNota" in nota:
        _add_generic_xml(root, "tipoNota", nota["tipoNota"])
    if "numNota" in nota:
        _add_generic_xml(root, "numNota", nota["numNota"])

    # Otros campos top-level (si existen y no son usuarios ni los anteriores)
    top_excluidos = {
        "numDocumentoIdObligado",
        "numFactura",
        "informacionesAdicionales",
        "tipoNota",
        "numNota",
        "usuarios",
    }
    for key, val in nota.items():
        if key in top_excluidos:
            continue
        _add_generic_xml(root, key, val)

    # Sección de usuarios: SOLO los usuarios que trae el JSON de la nota
    usuarios_el = ET.SubElement(root, "usuarios")
    for u in nota.get("usuarios", []):
        u_el = ET.SubElement(usuarios_el, "usuario")
        for k, v in u.items():
            if k == "servicios":
                serv_el = ET.SubElement(u_el, "servicios")
                if isinstance(v, dict):
                    for tipo_serv, lista in v.items():
                        t_el = ET.SubElement(serv_el, str(tipo_serv))
                        if isinstance(lista, list):
                            for item in lista:
                                it_el = ET.SubElement(t_el, "item")
                                if isinstance(item, dict):
                                    for kk, vv in item.items():
                                        c_el = ET.SubElement(it_el, str(kk))
                                        c_el.text = "" if vv is None else str(vv)
                                else:
                                    c_el = ET.SubElement(it_el, "valor")
                                    c_el.text = "" if item is None else str(item)
                continue

            _add_generic_xml(u_el, str(k), v)

    return root


def nota_json_a_xml_bytes(nota: Dict[str, Any]) -> bytes:
    """
    Serializa RipsDocumento con:
      - Pretty print
      - Encabezado: <?xml version="1.0" encoding="utf-8" standalone="no"?>
    """
    elem = nota_json_a_xml_element(nota)
    rough_xml = ET.tostring(elem, encoding="utf-8")
    dom = minidom.parseString(rough_xml)
    pretty = dom.toprettyxml(indent="  ")

    lineas = pretty.splitlines()
    if lineas and lineas[0].startswith("<?xml"):
        lineas[0] = '<?xml version="1.0" encoding="utf-8" standalone="no"?>'
    else:
        lineas.insert(0, '<?xml version="1.0" encoding="utf-8" standalone="no"?>')

    final = "\n".join(lineas)
    return final.encode("utf-8")


def incrustar_rips_en_attacheddocument_bytes(attached_bytes: bytes, rips_bytes: bytes) -> bytes:
    """
    Reemplaza el contenido del PRIMER:
        <cbc:Description><![CDATA[ ... ]]></cbc:Description>
    en un XML AttachedDocument ***RIPS*** por el XML de RipsDocumento.

    Bloquea explícitamente:
      - Plantillas que dentro del CDATA tengan <CreditNote ...> (Nota Crédito DIAN).
      - Plantillas que no tengan <RipsDocumento ...>.
    """
    # Decodificamos el XML de plantilla
    try:
        attached_text = attached_bytes.decode("utf-8")
    except UnicodeDecodeError:
        attached_text = attached_bytes.decode("latin-1")

    # XML de RipsDocumento nuevo
    rips_text = rips_bytes.decode("utf-8")

    # 1) Buscar la etiqueta <cbc:Description ...>
    desc_tag = "<cbc:Description"
    idx_desc = attached_text.find(desc_tag)
    if idx_desc == -1:
        raise ValueError(
            "No se encontró '<cbc:Description' en el XML de plantilla. "
            "Asegúrate de usar el AttachedDocument **RIPS**, no el XML de la Nota Crédito DIAN."
        )

    # 2) Buscar el <![CDATA[ después de <cbc:Description ...>
    idx_cdata = attached_text.find("<![CDATA[", idx_desc)
    if idx_cdata == -1:
        raise ValueError(
            "No se encontró '<![CDATA[' después de <cbc:Description> en la plantilla. "
            "Verifica que el AttachedDocument RIPS tenga el RipsDocumento dentro de CDATA."
        )

    # 3) Posición de inicio del contenido dentro del CDATA
    idx_content = idx_cdata + len("<![CDATA[")

    # 4) Buscar el final del CDATA + cierre de la etiqueta
    marker_end = "]]></cbc:Description>"
    idx_end = attached_text.find(marker_end, idx_content)
    if idx_end == -1:
        raise ValueError(
            "No se encontró ']]></cbc:Description>' en el XML de plantilla."
        )

    # 5) Extraer contenido original del CDATA
    original_cdata = attached_text[idx_content:idx_end]

    # Si en el CDATA hay <CreditNote>, claramente es una Nota Crédito DIAN, NO RIPS
    if "<CreditNote" in original_cdata or "<CreditNote" in original_cdata.replace(" ", ""):
        raise ValueError(
            "La plantilla XML corresponde a una Nota Crédito DIAN (tiene <CreditNote> en el CDATA). "
            "Esta NO es una plantilla RIPS. "
            "No uses aquí el XML de la Nota Crédito DIAN; usa el AttachedDocument RIPS "
            "(el que tiene <RipsDocumento> dentro del <![CDATA[ ... ]]>)."
        )

    # Validación: la plantilla DEBE tener <RipsDocumento> dentro del CDATA
    if "<RipsDocumento" not in original_cdata and "<RipsDocumento" not in original_cdata.replace(" ", ""):
        raise ValueError(
            "La plantilla XML no parece ser un AttachedDocument RIPS "
            "(no se encontró '<RipsDocumento>' dentro del CDATA). "
            "Probablemente estás usando un XML que no es RIPS."
        )

    # Validación: el XML nuevo también debe tener <RipsDocumento>
    if "<RipsDocumento" not in rips_text and "<RipsDocumento" not in rips_text.replace(" ", ""):
        raise ValueError(
            "El XML generado de la nota no contiene '<RipsDocumento>'. "
            "Revisa que el RipsDocumento se haya construido correctamente."
        )

    # 6) Reemplazar SOLO el contenido del CDATA por el nuevo RipsDocumento completo
    new_text = attached_text[:idx_content] + rips_text + attached_text[idx_end:]

    return new_text.encode("utf-8")


# ==========================
# Helpers de filtrado de nota
# ==========================

def construir_nota_filtrada_por_indices(nota: Dict[str, Any], indices: List[int]) -> Dict[str, Any]:
    """
    Construye una nueva nota a partir de la nota actual,
    dejando cabecera igual y filtrando 'usuarios' por los índices dados.
    """
    usuarios = nota.get("usuarios", []) or []
    nuevos_usuarios = []
    for i in indices:
        if 0 <= i < len(usuarios):
            nuevos_usuarios.append(usuarios[i])

    base = {k: v for k, v in nota.items() if k != "usuarios"}
    base["usuarios"] = nuevos_usuarios
    base = normalizar_documento_servicios(base)
    base = normalizar_codigos_usuarios(base)
    return base


# ==========================
# Helpers de sesión
# ==========================

def cargar_json_en_estado(uploaded_file, state_key: str, name_key: str) -> None:
    if uploaded_file is None:
        return
    nombre_subido = uploaded_file.name
    nombre_actual = st.session_state.get(name_key)
    if nombre_actual == nombre_subido and state_key in st.session_state:
        return
    try:
        data = json.load(uploaded_file)
    except Exception as exc:
        st.error(f"No se pudo leer el JSON '{nombre_subido}': {exc}")
        return
    st.session_state[state_key] = data
    st.session_state[name_key] = nombre_subido


def obtener_nota() -> Optional[Dict[str, Any]]:
    return st.session_state.get("nota_data")


def obtener_factura() -> Optional[Dict[str, Any]]:
    return st.session_state.get("factura_data")


# ==========================
# Interfaz Streamlit
# ==========================

def main():
    st.set_page_config(page_title="Asistente RIPS Notas Crédito", layout="wide")
    st.title("🧾 Asistente RIPS - Notas Crédito (JSON / XML RIPS / AttachedDocument)")

    st.sidebar.header("1️⃣ Cargar archivos")
    factura_file = st.sidebar.file_uploader("JSON FACTURA (referencia)", type=["json"])
    nota_file = st.sidebar.file_uploader("JSON NOTA (NC / incompleta o solo actualizados)", type=["json"])
    plantilla_file = st.sidebar.file_uploader("Plantilla masiva (xlsx o csv)", type=["xlsx", "csv"])
    attached_template_file = st.sidebar.file_uploader(
        "XML plantilla AttachedDocument RIPS",
        type=["xml"],
        help=(
            "Adjunta aquí el XML AttachedDocument **RIPS** (el que ya tiene "
            "<RipsDocumento> dentro del <![CDATA[ ... ]]>). "
            "NO pongas el XML de la Nota Crédito DIAN (el que tiene <CreditNote>)."
        ),
    )

    if "factura_data" not in st.session_state:
        st.session_state["factura_data"] = None
        st.session_state["factura_name"] = None
    if "nota_data" not in st.session_state:
        st.session_state["nota_data"] = None
        st.session_state["nota_name"] = None

    cargar_json_en_estado(factura_file, "factura_data", "factura_name")
    cargar_json_en_estado(nota_file, "nota_data", "nota_name")

    factura_data = obtener_factura()
    nota_data = obtener_nota()

    # Normalizaciones iniciales
    if factura_data:
        factura_data = normalizar_documento_servicios(factura_data)
        st.session_state["factura_data"] = factura_data
    if nota_data:
        nota_data = normalizar_documento_servicios(nota_data)
        nota_data = normalizar_codigos_usuarios(nota_data)
        st.session_state["nota_data"] = nota_data

    factura_data = obtener_factura()
    nota_data = obtener_nota()

    if not nota_data:
        st.warning("Sube al menos el JSON de la NOTA para empezar (puede ser completo o solo actualizados).")
        st.stop()

    # ==== 2. Encabezados ====
    st.markdown("### 2️⃣ Encabezados de factura y nota")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Factura (referencia)")
        if factura_data:
            st.json(
                {
                    "numDocumentoIdObligado": factura_data.get("numDocumentoIdObligado"),
                    "numFactura": factura_data.get("numFactura"),
                    "tipoNota": factura_data.get("tipoNota"),
                    "numNota": factura_data.get("numNota"),
                    "usuarios": len(factura_data.get("usuarios", [])),
                }
            )
        else:
            st.info("Opcional: carga la factura si quieres completar la nota con su información.")
    with c2:
        st.subheader("Nota (objetivo)")
        st.json(
            {
                "numDocumentoIdObligado": nota_data.get("numDocumentoIdObligado"),
                "numFactura": nota_data.get("numFactura"),
                "tipoNota": nota_data.get("tipoNota"),
                "numNota": nota_data.get("numNota"),
                "usuarios": len(nota_data.get("usuarios", [])),
            }
        )

    # ==== 3. Completar desde factura ====
    st.markdown("---")
    st.subheader("3️⃣ Completar NOTA desde FACTURA (demográficos + servicios vacíos)")

    if factura_data:
        col_a, col_b = st.columns([2, 1])
        with col_a:
            opcion_signo = st.selectbox(
                "Signo al copiar vrServicio / valorPagoModerador:",
                ("Dejar igual que factura", "Forzar POSITIVOS", "Forzar NEGATIVOS"),
            )
            signo = None
            if opcion_signo == "Forzar POSITIVOS":
                signo = 1
            elif opcion_signo == "Forzar NEGATIVOS":
                signo = -1
        with col_b:
            if st.button("Rellenar servicios vacíos + datos paciente desde factura"):
                nota_trabajo = copy.deepcopy(nota_data)
                nota_actualizada, resumen = copiar_servicios_factura_a_nota(
                    factura_data, nota_trabajo, signo
                )
                nota_actualizada = normalizar_documento_servicios(nota_actualizada)
                nota_actualizada = normalizar_codigos_usuarios(nota_actualizada)
                st.session_state["nota_data"] = nota_actualizada
                nota_data = nota_actualizada
                st.success(
                    f"Usuarios con servicios copiados: {resumen['usuarios_modificados']} | "
                    f"Demográficos completados: {resumen['usuarios_demografia_completada']} | "
                    f"Ya tenían servicios: {resumen['usuarios_ya_tenian_servicios']} | "
                    f"Sin coincidencia en factura: {len(resumen['usuarios_sin_encontrar'])}"
                )
    else:
        st.info("Si quieres rellenar desde la factura, cárgala en el panel lateral.")

    # ==== 4. Resumen usuarios ====
    st.markdown("---")
    st.subheader("4️⃣ Resumen de usuarios en la NOTA")

    df_resumen = generar_resumen_usuarios(nota_data)
    if df_resumen.empty:
        st.warning("La nota no contiene usuarios.")
    else:
        col_tabla, col_info = st.columns([3, 1])
        with col_tabla:
            st.dataframe(df_resumen, use_container_width=True, height=350)
        with col_info:
            total = len(df_resumen)
            incompletos = (df_resumen["estadoServicios"] == "INCOMPLETO").sum()
            st.metric("Usuarios totales", total)
            st.metric("Con servicios incompletos", incompletos)

    # ==== 5. Edición individual ====
    st.markdown("---")
    st.subheader("5️⃣ Edición individual (JSON por usuario)")

    usuarios_nota = nota_data.get("usuarios", [])
    if usuarios_nota:
        max_idx = len(usuarios_nota) - 1
        idx_sel = st.number_input(
            "Índice de usuario a editar",
            min_value=0,
            max_value=max_idx,
            value=0,
            step=1,
        )
        usuario = usuarios_nota[idx_sel]

        st.write(
            f"Usuario **{idx_sel}** — "
            f"{usuario.get('tipoDocumentoIdentificacion')} "
            f"{usuario.get('numDocumentoIdentificacion')}"
        )

        claves_esperadas = obtener_claves_servicio_esperadas(factura_data, nota_data)
        filas_nota = desglosar_servicios_usuario(usuario, claves_esperadas)

        datos_paciente = {k: v for k, v in usuario.items() if k != "servicios"}
        with st.expander("📋 Datos del paciente (NOTA)", expanded=True):
            st.json(datos_paciente)

        servicios_visibles = usuario.get("servicios", {}) or {}
        if filas_nota:
            st.markdown("**Servicios del usuario (NOTA):**")
            st.dataframe(pd.DataFrame(filas_nota), use_container_width=True, height=260)
        else:
            st.info("Este usuario no tiene servicios en la nota.")

        servicios_str = json.dumps(servicios_visibles, ensure_ascii=False, indent=2)
        servicios_editados = st.text_area(
            "Editar JSON de `servicios` (se guarda en la NOTA):",
            value=servicios_str,
            height=260,
            key=f"servicios_usuario_{idx_sel}",
        )

        if st.button("Guardar SOLO servicios de este usuario"):
            try:
                nuevos_servicios = json.loads(servicios_editados)
            except json.JSONDecodeError as exc:
                st.error(f"JSON de servicios inválido: {exc}")
            else:
                usuario["servicios"] = nuevos_servicios
                normalizar_servicios_usuario(usuario)
                usuarios_nota[idx_sel] = usuario
                nota_data["usuarios"] = usuarios_nota
                nota_data = normalizar_codigos_usuarios(nota_data)
                st.session_state["nota_data"] = nota_data
                st.success("Servicios actualizados para este usuario en la NOTA.")

        with st.expander("⚙️ Edición avanzada: usuario completo", expanded=False):
            usuario_str = json.dumps(usuario, ensure_ascii=False, indent=2)
            usuario_editado = st.text_area(
                "JSON completo del usuario (se guarda en la NOTA):",
                value=usuario_str,
                height=260,
                key=f"usuario_completo_{idx_sel}",
            )
            if st.button("Guardar usuario completo (NOTA)", key=f"btn_usuario_completo_{idx_sel}"):
                try:
                    nuevo_u = json.loads(usuario_editado)
                except json.JSONDecodeError as exc:
                    st.error(f"JSON del usuario inválido: {exc}")
                else:
                    if not isinstance(nuevo_u, dict):
                        st.error("El usuario debe ser un objeto JSON (dict).")
                    else:
                        normalizar_servicios_usuario(nuevo_u)
                        usuarios_nota[idx_sel] = nuevo_u
                        nota_data["usuarios"] = usuarios_nota
                        nota_data = normalizar_codigos_usuarios(nota_data)
                        st.session_state["nota_data"] = nota_data
                        st.success("Usuario completo actualizado en la NOTA.")
    else:
        st.info("No hay usuarios en la nota para editar.")

    # ==== 6. Edición masiva ====
    st.markdown("---")
    st.subheader("6️⃣ Edición masiva (plantilla Excel/CSV)")

    campos_paciente_txt = "`, `".join(CAMPOS_PACIENTE)
    st.markdown(
        f"""
        - Cada fila de la plantilla representa **un servicio** de **un usuario**.
        - Campos clave:
          - `idx_usuario`, `tipo_servicio`, `idx_item`, `vrServicio_factura`, `vrServicio_nota`.
        - Puedes corregir demográficos también:
          - `{campos_paciente_txt}`.
        - Solo se aplica el cambio de servicio cuando `vrServicio_nota` tiene valor.
        """
    )

    col_pl1, col_pl2 = st.columns(2)
    with col_pl1:
        buffer, ext, mime = generar_plantilla_servicios(nota_data, factura_data)
        st.download_button(
            "⬇️ Descargar plantilla de servicios",
            data=buffer,
            file_name=f"plantilla_servicios_rips.{ext}",
            mime=mime,
        )

    with col_pl2:
        if plantilla_file is not None and st.button("Aplicar cambios desde plantilla"):
            nota_actualizada, errores = aplicar_plantilla_servicios(
                nota_data,
                factura_data,
                plantilla_file,
            )
            nota_actualizada = normalizar_documento_servicios(nota_actualizada)
            nota_actualizada = normalizar_codigos_usuarios(nota_actualizada)
            st.session_state["nota_data"] = nota_actualizada
            nota_data = nota_actualizada
            if errores:
                st.warning("Se aplicaron los cambios con las siguientes observaciones:")
                for e in errores:
                    st.write("- ", e)
            else:
                st.success("Plantilla aplicada correctamente sin observaciones.")

    # ==== 7. Exportar JSON/XML completos ====
    st.markdown("---")
    st.subheader("7️⃣ Descargar JSON / XML interno (RipsDocumento) de la NOTA actual")

    nota_data = normalizar_codigos_usuarios(nota_data)
    st.session_state["nota_data"] = nota_data

    nota_json_bytes = json.dumps(nota_data, ensure_ascii=False, indent=2).encode("utf-8")
    xml_bytes = nota_json_a_xml_bytes(nota_data)
    base_name = (st.session_state.get("nota_name") or "nota_corregida").rsplit(".", 1)[0]

    col_ex1, col_ex2 = st.columns(2)
    with col_ex1:
        st.download_button(
            "⬇️ JSON de la nota (tal como está cargada)",
            data=nota_json_bytes,
            file_name=f"{base_name}_corregida.json",
            mime="application/json",
        )
    with col_ex2:
        st.download_button(
            "⬇️ XML interno RipsDocumento (NO es XML DIAN)",
            data=xml_bytes,
            file_name=f"{base_name}_RipsDocumento.xml",
            mime="application/xml",
        )

    # ==== 8. Exportar solo usuarios actualizados (desde Excel) ====
    st.markdown("---")
    st.subheader("8️⃣ Exportar solo usuarios con nota crédito aplicada (desde plantilla masiva)")

    usuarios_actuales = nota_data.get("usuarios", []) or []
    updated_from_excel = st.session_state.get("usuarios_actualizados_desde_excel", [])
    updated_set = set(updated_from_excel)

    if not usuarios_actuales:
        st.info("La nota no tiene usuarios.")
    elif not updated_set:
        st.info(
            "Aún no hay usuarios marcados como actualizados desde Excel. "
            "Puedes usar simplemente el JSON actual si ya contiene solo los pacientes que necesitas."
        )
    else:
        opciones: Dict[str, int] = {}
        for idx, u in enumerate(usuarios_actuales):
            if idx in updated_set and tiene_lista_con_items(u.get("servicios")):
                label = f"{idx} - {u.get('tipoDocumentoIdentificacion','')} {u.get('numDocumentoIdentificacion','')}"
                opciones[label] = idx

        if not opciones:
            st.info("No se encontraron usuarios con servicios y marcados como actualizados desde Excel.")
        else:
            filas = []
            for label, idx in opciones.items():
                u = usuarios_actuales[idx]
                filas.append(
                    {
                        "idx": idx,
                        "tipoDocumentoIdentificacion": u.get("tipoDocumentoIdentificacion"),
                        "numDocumentoIdentificacion": u.get("numDocumentoIdentificacion"),
                    }
                )
            st.dataframe(pd.DataFrame(filas), use_container_width=True, height=200)

            indices_todos = sorted(opciones.values())
            nota_filtrada_todos = construir_nota_filtrada_por_indices(nota_data, indices_todos)

            json_todos_bytes = json.dumps(
                nota_filtrada_todos, ensure_ascii=False, indent=2
            ).encode("utf-8")
            xml_todos_bytes = nota_json_a_xml_bytes(nota_filtrada_todos)

            col_t1, col_t2 = st.columns(2)
            with col_t1:
                st.download_button(
                    "⬇️ JSON solo usuarios con nota aplicada",
                    data=json_todos_bytes,
                    file_name=f"{base_name}_solo_actualizados.json",
                    mime="application/json",
                )
            with col_t2:
                st.download_button(
                    "⬇️ XML RipsDocumento solo usuarios con nota aplicada",
                    data=xml_todos_bytes,
                    file_name=f"{base_name}_RipsDocumento_solo_actualizados.xml",
                    mime="application/xml",
                )

            st.markdown("**(Opcional) Exportar un subconjunto de esos usuarios**")
            seleccion = st.multiselect(
                "Selecciona usuarios específicos:",
                list(opciones.keys()),
            )
            if seleccion:
                idxs_sel = [opciones[s] for s in seleccion]
                nota_sel = construir_nota_filtrada_por_indices(nota_data, idxs_sel)

                json_sel_bytes = json.dumps(
                    nota_sel, ensure_ascii=False, indent=2
                ).encode("utf-8")
                xml_sel_bytes = nota_json_a_xml_bytes(nota_sel)

                col_s1, col_s2 = st.columns(2)
                with col_s1:
                    st.download_button(
                        "⬇️ JSON usuarios seleccionados",
                        data=json_sel_bytes,
                        file_name=f"{base_name}_seleccionados.json",
                        mime="application/json",
                    )
                with col_s2:
                    st.download_button(
                        "⬇️ XML RipsDocumento usuarios seleccionados",
                        data=xml_sel_bytes,
                        file_name=f"{base_name}_RipsDocumento_seleccionados.xml",
                        mime="application/xml",
                    )

    # ==== 9. AttachedDocument completo con RipsDocumento dentro ====
    st.markdown("---")
    st.subheader("9️⃣ Generar XML AttachedDocument RIPS (plantilla + RipsDocumento)")

    if attached_template_file is None:
        st.info(
            "Para usar un AttachedDocument RIPS como en tu ejemplo, carga en el panel lateral el XML "
            "AttachedDocument **RIPS** que ya genera tu sistema (el que tiene "
            "<RipsDocumento> dentro del <![CDATA[ ... ]]>). "
            "Aquí solo se reemplaza ese RipsDocumento interno por uno nuevo "
            "con los usuarios y valores que haya en el JSON de la nota."
        )
    else:
        modo_rips = st.radio(
            "¿Qué usuarios incluir en el RipsDocumento del AttachedDocument?",
            (
                "Todos los usuarios de la nota actual",
                "Solo usuarios con nota aplicada (según plantilla Excel)",
            ),
        )

        if modo_rips == "Solo usuarios con nota aplicada (según plantilla Excel)":
            updated_idx = st.session_state.get("usuarios_actualizados_desde_excel", [])
            if updated_idx:
                nota_para_xml = construir_nota_filtrada_por_indices(nota_data, updated_idx)
            else:
                st.warning(
                    "No hay usuarios marcados como actualizados desde Excel. "
                    "Se usará la nota tal como está cargada (todos sus usuarios)."
                )
                nota_para_xml = nota_data
        else:
            # Usa exactamente los usuarios que tenga el JSON de la nota actual
            nota_para_xml = nota_data

        if st.button("Generar AttachedDocument con RipsDocumento incrustado"):
            try:
                attached_bytes = attached_template_file.getvalue()
                rips_bytes = nota_json_a_xml_bytes(nota_para_xml)
                attached_rips_bytes = incrustar_rips_en_attacheddocument_bytes(
                    attached_bytes, rips_bytes
                )
            except Exception as exc:
                st.error(
                    f"No se pudo incrustar el RipsDocumento en el AttachedDocument: {exc}"
                )
            else:
                st.success(
                    "Se generó el XML AttachedDocument RIPS manteniendo toda la estructura original "
                    "y reemplazando solo el RipsDocumento interno (pacientes según el JSON actual / Excel)."
                )
                st.download_button(
                    "⬇️ Descargar AttachedDocument RIPS",
                    data=attached_rips_bytes,
                    file_name=f"{base_name}_AttachedDocument_RIPS.xml",
                    mime="application/xml",
                )


if __name__ == "__main__":
    main()
