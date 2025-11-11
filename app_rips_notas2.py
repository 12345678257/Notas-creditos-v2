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

# Campos demográficos del paciente a nivel de usuario
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

# Grupos de servicios esperados en la estructura de la nota
SERVICIO_GRUPOS = [
    "consultas",
    "procedimientos",
    "urgencias",
    "hospitalizacion",
    "recienNacidos",
    "medicamentos",
    "otrosServicios",
]


# ==========================
# Utilidades de negocio
# ==========================

def tiene_lista_con_items(servicios: Any) -> bool:
    """Retorna True si el diccionario 'servicios' tiene al menos una lista con 1 item."""
    if not isinstance(servicios, dict):
        return False
    for v in servicios.values():
        if isinstance(v, list) and len(v) > 0:
            return True
    return False


def ajustar_signo_servicios(servicios: Dict[str, Any], signo: int) -> None:
    """
    Multiplica por 'signo' algunos campos numéricos típicos de RIPS en todas las listas de servicios.
    Esto permite, por ejemplo, convertir una factura en nota crédito usando valores negativos.
    """
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
    """
    Asegura que el usuario tenga la estructura completa de 'servicios' con todos los grupos
    ['consultas','procedimientos','urgencias','hospitalizacion','recienNacidos','medicamentos','otrosServicios'].
    """
    serv = usuario.get("servicios")
    if not isinstance(serv, dict):
        serv = {}
    for grupo in SERVICIO_GRUPOS:
        lista = serv.get(grupo)
        if not isinstance(lista, list):
            serv[grupo] = []
    usuario["servicios"] = serv


def normalizar_documento_servicios(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza la estructura de servicios de todos los usuarios del documento (factura o nota).
    """
    usuarios = doc.get("usuarios")
    if not isinstance(usuarios, list):
        return doc
    for i, u in enumerate(usuarios):
        if isinstance(u, dict):
            normalizar_servicios_usuario(u)
            usuarios[i] = u
    doc["usuarios"] = usuarios
    return doc


def copiar_servicios_factura_a_nota(
    factura: Dict[str, Any],
    nota: Dict[str, Any],
    forzar_signo: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Completa la NOTA a partir de la FACTURA:

    - Empareja pacientes por tipoDocumentoIdentificacion + numDocumentoIdentificacion (y si falla, por número).
    - Completa campos demográficos faltantes en la nota con los de la factura.
    - Si el usuario en la nota NO tiene ningún servicio (todas las listas vacías),
      copia todos los servicios desde la factura (misma estructura).
    """
    inv_users = factura.get("usuarios", [])
    note_users = nota.get("usuarios", [])

    # Mapear usuarios de la factura
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
        key_full = (tipo, num)

        u_fact = inv_map_full.get(key_full) or inv_map_by_num.get(num or "")

        if u_fact is None:
            usuarios_sin_encontrar.append(key_full)
            continue

        # Completar datos demográficos del paciente si faltan
        campos_actualizados = []
        for campo in CAMPOS_PACIENTE:
            val_nota = u.get(campo, None)
            if val_nota in (None, ""):
                val_fact = u_fact.get(campo, None)
                if val_fact not in (None, ""):
                    u[campo] = val_fact
                    campos_actualizados.append(campo)
        if campos_actualizados:
            usuarios_demografia_completada += 1

        # Normalizar estructura de servicios de la factura y la nota
        normalizar_servicios_usuario(u_fact)
        normalizar_servicios_usuario(u)

        if tiene_lista_con_items(u.get("servicios")):
            # Ya tenía servicios con al menos un item
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

    resumen = {
        "total_usuarios_factura": len(inv_users),
        "total_usuarios_nota": len(note_users),
        "usuarios_modificados": usuarios_modificados,
        "usuarios_ya_tenian_servicios": usuarios_ya_tenian_servicios,
        "usuarios_demografia_completada": usuarios_demografia_completada,
        "usuarios_sin_encontrar": usuarios_sin_encontrar,
    }
    return nota, resumen


def validar_estructura_servicios(nota: Dict[str, Any]) -> List[int]:
    """Índices de usuarios sin ninguna lista de servicios con ítems."""
    malos: List[int] = []
    for i, u in enumerate(nota.get("usuarios", [])):
        if not tiene_lista_con_items(u.get("servicios")):
            malos.append(i)
    return malos


def generar_resumen_usuarios(nota: Dict[str, Any]) -> pd.DataFrame:
    """
    Tabla resumen por usuario:
    - idx
    - tipoDocumentoIdentificacion
    - numDocumentoIdentificacion
    - estadoServicios (OK / INCOMPLETO)
    - numListasServicios
    - totalItemsServicios
    """
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


# ==========================
# Claves esperadas y desglose
# ==========================

def obtener_claves_servicio_esperadas(
    factura: Optional[Dict[str, Any]],
    nota: Optional[Dict[str, Any]],
) -> List[str]:
    """
    Obtiene el conjunto de claves esperadas para un item de servicio
    tomando el item más "completo" (con más campos) entre factura y nota.
    Así sabemos qué campos deberían ir en cada servicio.
    """
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
    """
    Convierte los servicios de un usuario en filas planas, una por item,
    incluyendo qué campos están vacíos o en None, comparados contra las claves esperadas.
    """
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
                valor = item.get(clave)
                fila[clave] = valor
                if valor in (None, ""):
                    faltantes.append(clave)
            fila["campos_faltantes"] = ",".join(faltantes)
            filas.append(fila)

    return filas


# ==========================
# Plantilla masiva por servicio
# ==========================

def generar_plantilla_servicios(
    nota: Dict[str, Any],
    factura: Optional[Dict[str, Any]],
) -> Tuple[BytesIO, str, str]:
    """
    Genera plantilla para edición masiva de servicios, centrada en la NOTA.
    - Cada fila = 1 servicio de 1 usuario de la nota.
    - vrServicio_nota se llena con el valor actual de la nota si existe.
    - Si hay factura, se trae vrServicio_factura como referencia (mismo idx_usuario/tipo_servicio/idx_item).
    - Si en la nota un usuario no tiene estructura de servicios pero sí existe en la factura,
      se generan filas base para ese usuario usando la factura.
    - Además incluye campos demográficos del paciente (CAMPOS_PACIENTE) por fila.
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

        map_fac: Dict[Tuple[str, int], Dict[str, Any]] = {}
        for f in filas_fac:
            key = (f["tipo_servicio"], f["idx_item"])
            map_fac[key] = f

        def agregar_campos_paciente(base: Dict[str, Any]):
            for campo in CAMPOS_PACIENTE:
                if u_nota is not None and campo in u_nota:
                    base[campo] = u_nota.get(campo)
                elif u_fac is not None and campo in u_fac:
                    base[campo] = u_fac.get(campo)
                else:
                    base[campo] = None

        if filas_nota:
            # Usuario ya tiene servicios en la nota
            for f in filas_nota:
                key = (f["tipo_servicio"], f["idx_item"])
                base_fac = map_fac.get(key, {})
                fila = {
                    "idx_usuario": idx_u,
                    "tipo_servicio": f["tipo_servicio"],
                    "idx_item": f["idx_item"],
                    "vrServicio_factura": base_fac.get("vrServicio") if base_fac else None,
                    "vrServicio_nota": f.get("vrServicio"),
                    "campos_faltantes_nota": f.get("campos_faltantes", ""),
                }
                agregar_campos_paciente(fila)
                filas.append(fila)
        else:
            # Usuario no tiene servicios en la nota; si hay en factura, generamos filas base
            for f in filas_fac:
                fila = {
                    "idx_usuario": idx_u,
                    "tipo_servicio": f["tipo_servicio"],
                    "idx_item": f["idx_item"],
                    "vrServicio_factura": f.get("vrServicio"),
                    "vrServicio_nota": None,
                    "campos_faltantes_nota": "TODOS (usuario sin estructura de servicios en nota)",
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
    except (ModuleNotFoundError, ImportError):
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
    Aplica los cambios de vrServicio_nota contenidos en la plantilla (xlsx o csv).
    - Si la nota ya tiene la estructura de servicios para esa fila, solo actualiza vrServicio.
    - Si la nota NO tiene esa estructura pero sí existe en la factura, copia la línea de la factura
      y luego actualiza vrServicio.
    - Además, si la plantilla trae columnas de CAMPOS_PACIENTE, actualiza esos campos
      a nivel de usuario en la nota (último valor registrado para ese usuario gana).
    """
    errores: List[str] = []

    try:
        nombre = getattr(archivo_plantilla, "name", "") or ""
        if nombre.lower().endswith(".csv"):
            df = pd.read_csv(archivo_plantilla)
        else:
            df = pd.read_excel(archivo_plantilla)
    except Exception as exc:
        errores.append(f"No se pudo leer el archivo de plantilla (xlsx/csv): {exc}")
        return nota, errores

    obligatorias = ["idx_usuario", "tipo_servicio", "idx_item", "vrServicio_nota"]
    for col in obligatorias:
        if col not in df.columns:
            errores.append(f"Falta columna obligatoria '{col}' en la plantilla.")
            return nota, errores

    usuarios_nota = nota.get("usuarios", [])
    usuarios_fac = factura.get("usuarios", []) if factura else []

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
            # Si no diligenciaron valor de nota, no tocamos ese servicio
            continue

        if not (0 <= idx_u < len(usuarios_nota)):
            errores.append(f"Índice de usuario {idx_u} fuera de rango en la nota.")
            continue

        usuario_nota = usuarios_nota[idx_u]

        # Actualizar campos demográficos del paciente desde la plantilla (si vienen)
        for campo in CAMPOS_PACIENTE:
            if campo in df.columns:
                valor_campo = fila[campo]
                if not pd.isna(valor_campo):
                    if campo == "consecutivo":
                        try:
                            valor_campo = int(valor_campo)
                        except Exception:
                            pass
                    usuario_nota[campo] = valor_campo

        servicios_nota = usuario_nota.get("servicios")
        if not isinstance(servicios_nota, dict):
            servicios_nota = {}
            usuario_nota["servicios"] = servicios_nota

        lista = servicios_nota.get(tipo_serv)

        # Si la estructura no existe aún en la nota, intentamos copiarla desde la factura
        if not (isinstance(lista, list) and idx_item < len(lista)):
            if not factura:
                errores.append(
                    f"No existe estructura de servicios para usuario {idx_u}, "
                    f"tipo '{tipo_serv}', ítem {idx_item} y no hay factura cargada."
                )
                usuarios_nota[idx_u] = usuario_nota
                continue
            if not (0 <= idx_u < len(usuarios_fac)):
                errores.append(
                    f"No se encontró el usuario {idx_u} en la factura para crear la estructura de servicios."
                )
                usuarios_nota[idx_u] = usuario_nota
                continue
            usuario_fac = usuarios_fac[idx_u]
            servicios_fac = usuario_fac.get("servicios", {})
            lista_fac = servicios_fac.get(tipo_serv)
            if not (isinstance(lista_fac, list) and idx_item < len(lista_fac)):
                errores.append(
                    f"No se encontró línea base en factura para usuario {idx_u}, "
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
                f"No se pudo asegurar la estructura de servicios para usuario {idx_u}, "
                f"tipo '{tipo_serv}', ítem {idx_item}."
            )
            usuarios_nota[idx_u] = usuario_nota
            continue

        item_nota = lista[idx_item]

        try:
            valor_nota = float(vr_nota)
        except Exception:
            errores.append(
                f"Valor de vrServicio_nota inválido para usuario {idx_u}, "
                f"tipo '{tipo_serv}', ítem {idx_item}: {vr_nota}"
            )
            usuarios_nota[idx_u] = usuario_nota
            continue

        item_nota["vrServicio"] = valor_nota
        lista[idx_item] = item_nota
        servicios_nota[tipo_serv] = lista
        usuario_nota["servicios"] = servicios_nota
        usuarios_nota[idx_u] = usuario_nota

    nota["usuarios"] = usuarios_nota
    return nota, errores


# ==========================
# JSON -> XML (genérico)
# ==========================

def nota_json_a_xml_element(nota: Dict[str, Any]) -> ET.Element:
    """
    XML genérico para visualizar/exportar el contenido del JSON.
    No es un XML oficial del Minsalud, solo una representación estructurada.
    """
    root = ET.Element("RipsDocumento")
    for key, val in nota.items():
        if key == "usuarios":
            continue
        child = ET.SubElement(root, key)
        child.text = "" if val is None else str(val)

    usuarios_el = ET.SubElement(root, "usuarios")
    for u in nota.get("usuarios", []):
        u_el = ET.SubElement(usuarios_el, "usuario")
        for key, val in u.items():
            if key == "servicios":
                serv_el = ET.SubElement(u_el, "servicios")
                if isinstance(val, dict):
                    for tipo_serv, lista in val.items():
                        tipo_el = ET.SubElement(serv_el, str(tipo_serv))
                        if isinstance(lista, list):
                            for item in lista:
                                item_el = ET.SubElement(tipo_el, "item")
                                if isinstance(item, dict):
                                    for kk, vv in item.items():
                                        campo_el = ET.SubElement(item_el, str(kk))
                                        campo_el.text = "" if vv is None else str(vv)
                continue
            campo_el = ET.SubElement(u_el, str(key))
            campo_el.text = "" if val is None else str(val)
    return root


def nota_json_a_xml_bytes(nota: Dict[str, Any]) -> bytes:
    elem = nota_json_a_xml_element(nota)
    rough_xml = ET.tostring(elem, encoding="utf-8")
    dom = minidom.parseString(rough_xml)
    pretty = dom.toprettyxml(indent="  ", encoding="utf-8")
    return pretty


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
    st.set_page_config(page_title="Asistente RIPS JSON / Notas Crédito", layout="wide")
    st.title("🧾 Asistente RIPS JSON / Notas Crédito")

    st.write(
        "Cargue la **factura (JSON completo)** y la **nota/crédito o archivo RIPS incompleto** en JSON. "
        "La aplicación trabaja SIEMPRE sobre el JSON de la NOTA, usando la factura solo como referencia "
        "para completar o comparar servicios."
    )

    # ---- Sidebar: carga de archivos ----
    st.sidebar.header("1️⃣ Cargar archivos")

    factura_file = st.sidebar.file_uploader(
        "JSON de referencia (Factura completa)", type=["json"], key="factura_uploader"
    )
    nota_file = st.sidebar.file_uploader(
        "JSON a corregir (Nota crédito / RIPS)", type=["json"], key="nota_uploader"
    )
    plantilla_file = st.sidebar.file_uploader(
        "Plantilla con servicios actualizados (xlsx o csv, opcional)",
        type=["xlsx", "csv"],
        key="plantilla_uploader",
    )

    # Inicializar estado
    if "factura_data" not in st.session_state:
        st.session_state["factura_data"] = None
        st.session_state["factura_name"] = None
    if "nota_data" not in st.session_state:
        st.session_state["nota_data"] = None
        st.session_state["nota_name"] = None

    # Cargar JSONs a sesión
    cargar_json_en_estado(factura_file, "factura_data", "factura_name")
    cargar_json_en_estado(nota_file, "nota_data", "nota_name")

    factura_data = obtener_factura()
    nota_data = obtener_nota()

    # Registrar nota original una sola vez por archivo cargado
    if nota_data:
        current_name = st.session_state.get("nota_name")
        original_name = st.session_state.get("nota_original_name")
        if original_name != current_name:
            st.session_state["nota_original_name"] = current_name
            st.session_state["nota_original_data"] = copy.deepcopy(nota_data)
            tmp = normalizar_documento_servicios(copy.deepcopy(nota_data))
            st.session_state["usuarios_incompletos_original"] = validar_estructura_servicios(tmp)

    # Normalizar estructuras de servicios según la estructura oficial
    if factura_data:
        factura_data = normalizar_documento_servicios(factura_data)
        st.session_state["factura_data"] = factura_data
    if nota_data:
        nota_data = normalizar_documento_servicios(nota_data)
        st.session_state["nota_data"] = nota_data

    factura_data = obtener_factura()
    nota_data = obtener_nota()

    # Modo de trabajo
    modo_trabajo = st.sidebar.radio(
        "Modo de trabajo con servicios",
        (
            "Solo JSON de la NOTA",
            "Usar FACTURA como referencia si la NOTA está vacía",
        ),
        index=1 if factura_data else 0,
    )
    usar_factura = (modo_trabajo == "Usar FACTURA como referencia si la NOTA está vacía")

    col_meta1, col_meta2 = st.columns(2)

    with col_meta1:
        st.subheader("📄 Factura / JSON de referencia")
        if factura_data:
            st.markdown(f"**Archivo:** `{st.session_state.get('factura_name')}`")
            st.json(
                {
                    "numDocumentoIdObligado": factura_data.get("numDocumentoIdObligado"),
                    "numFactura": factura_data.get("numFactura"),
                    "tipoNota": factura_data.get("tipoNota"),
                    "numNota": factura_data.get("numNota"),
                    "totalUsuarios": len(factura_data.get("usuarios", [])),
                }
            )
        else:
            st.info("Suba un JSON de factura completa (opcional).")

    with col_meta2:
        st.subheader("🧾 Nota / JSON a corregir (SE EDITA ESTE)")
        if nota_data:
            st.markdown(f"**Archivo:** `{st.session_state.get('nota_name')}`")
            st.json(
                {
                    "numDocumentoIdObligado": nota_data.get("numDocumentoIdObligado"),
                    "numFactura": nota_data.get("numFactura"),
                    "tipoNota": nota_data.get("tipoNota"),
                    "numNota": nota_data.get("numNota"),
                    "totalUsuarios": len(nota_data.get("usuarios", [])),
                }
            )
        else:
            st.info("Suba el JSON de la nota/crédito o archivo RIPS incompleto.")

    if not nota_data:
        st.stop()

    # ---- 2. Cabezote de la nota ----
    st.markdown("---")
    st.subheader("2️⃣ Cabezote de la nota (JSON raíz sin usuarios)")

    header = {k: v for k, v in nota_data.items() if k != "usuarios"}

    col_head_view, col_head_edit = st.columns(2)

    with col_head_view:
        st.markdown("**Vista actual del cabezote:**")
        st.json(header)

    with col_head_edit:
        header_str = st.text_area(
            "Editar cabezote de la nota (JSON). No incluya el campo 'usuarios'.",
            value=json.dumps(header, ensure_ascii=False, indent=2),
            height=260,
        )
        if st.button("Guardar cambios en cabezote"):
            try:
                nuevo_header = json.loads(header_str)
            except json.JSONDecodeError as exc:
                st.error(f"El JSON del cabezote no es válido: {exc}")
            else:
                if not isinstance(nuevo_header, dict):
                    st.error("El cabezote debe ser un objeto JSON (dict).")
                else:
                    usuarios = nota_data.get("usuarios", [])
                    nota_data = copy.deepcopy(nuevo_header)
                    nota_data["usuarios"] = usuarios
                    nota_data = normalizar_documento_servicios(nota_data)
                    st.session_state["nota_data"] = nota_data
                    st.success("Cabezote actualizado correctamente en la nota.")

    # Releer después del posible cambio de cabezote
    nota_data = st.session_state["nota_data"]

    # Claves esperadas (según modo)
    claves_esperadas = obtener_claves_servicio_esperadas(
        factura_data if usar_factura else None,
        nota_data,
    )

    # ---- 3. Resumen usuarios ----
    st.markdown("---")
    st.subheader("3️⃣ Resumen y validación de usuarios (NOTA)")

    df_resumen = generar_resumen_usuarios(nota_data)
    if df_resumen.empty:
        st.warning("El JSON de la nota no contiene usuarios.")
    else:
        col_tabla, col_info = st.columns([3, 1])
        with col_tabla:
            st.dataframe(df_resumen, use_container_width=True, height=400)
        with col_info:
            total = len(df_resumen)
            incompletos = (df_resumen["estadoServicios"] == "INCOMPLETO").sum()
            st.metric("Usuarios totales", total)
            st.metric("Usuarios con servicios incompletos", incompletos)
            if incompletos == 0:
                st.success("Todos los usuarios tienen al menos una lista de servicios con 1 ítem.")
            else:
                st.error(
                    "Hay usuarios con 'servicios' vacío o sin listas con ítems. "
                    "Puede rellenarlos automáticamente desde la factura, "
                    "editar un usuario puntual o usar la plantilla masiva."
                )

    # ---- 4. Copiar servicios desde factura ----
    st.markdown("---")
    st.subheader("4️⃣ Completar nota desde JSON de la factura (opcional)")

    if not factura_data:
        st.info(
            "Si la nota viene sin `servicios`, cargue la factura para poder copiar la estructura "
            "hacia la nota (este paso es opcional)."
        )
    else:
        col_signo, col_boton = st.columns([2, 1])
        with col_signo:
            opcion_signo = st.selectbox(
                "Manejo del signo en `vrServicio` y `valorPagoModerador`:",
                (
                    "Dejar igual que la factura",
                    "Forzar valores POSITIVOS",
                    "Forzar valores NEGATIVOS",
                ),
            )
            signo = None
            if opcion_signo == "Forzar valores POSITIVOS":
                signo = 1
            elif opcion_signo == "Forzar valores NEGATIVOS":
                signo = -1
        with col_boton:
            if st.button("Rellenar servicios vacíos y completar datos desde factura"):
                nota_trabajo = copy.deepcopy(nota_data)
                nota_actualizada, resumen = copiar_servicios_factura_a_nota(
                    factura_data, nota_trabajo, signo
                )
                nota_actualizada = normalizar_documento_servicios(nota_actualizada)
                st.session_state["nota_data"] = nota_actualizada
                nota_data = nota_actualizada
                st.success(
                    f"Usuarios modificados (servicios copiados): {resumen['usuarios_modificados']}, "
                    f"usuarios con datos del paciente completados: {resumen['usuarios_demografia_completada']}, "
                    f"ya tenían servicios: {resumen['usuarios_ya_tenian_servicios']}, "
                    f"sin coincidencia en factura: {len(resumen['usuarios_sin_encontrar'])}."
                )

    # ---- 5. Edición individual ----
    st.markdown("---")
    st.subheader("5️⃣ Edición individual de usuarios y servicios (NOTA)")

    usuarios_nota = nota_data.get("usuarios", [])
    if not usuarios_nota:
        st.warning("La nota no tiene usuarios para editar.")
    else:
        max_idx = len(usuarios_nota) - 1
        idx_sel = st.number_input(
            "Seleccione el índice de usuario a editar",
            min_value=0,
            max_value=max_idx,
            value=0,
            step=1,
        )
        usuario_nota = usuarios_nota[idx_sel]

        st.write(
            f"Usuario índice **{idx_sel}** – "
            f"{usuario_nota.get('tipoDocumentoIdentificacion')} "
            f"{usuario_nota.get('numDocumentoIdentificacion')}"
        )

        # Datos demográficos del paciente (nota)
        datos_paciente = {k: v for k, v in usuario_nota.items() if k != "servicios"}
        with st.expander("📋 Datos del paciente (JSON de la NOTA)", expanded=True):
            st.json(datos_paciente)

        # Servicios de la nota
        filas_nota = desglosar_servicios_usuario(usuario_nota, claves_esperadas)

        # Servicios de la factura para este usuario (solo si modo lo permite)
        usuario_fac = None
        filas_fac: List[Dict[str, Any]] = []
        if usar_factura and factura_data:
            usuarios_fac = factura_data.get("usuarios", [])
            if 0 <= idx_sel < len(usuarios_fac):
                usuario_fac = usuarios_fac[idx_sel]
                filas_fac = desglosar_servicios_usuario(usuario_fac, claves_esperadas)

        if filas_nota:
            st.markdown("**Servicios del usuario según la NOTA (campos faltantes al final):**")
            st.dataframe(pd.DataFrame(filas_nota), use_container_width=True, height=260)
            servicios_visuales = usuario_nota.get("servicios", {})
        elif filas_fac:
            st.markdown(
                "**Este usuario no tiene servicios cargados en la NOTA, "
                "pero sí en la FACTURA (modo referencia). Se muestran los servicios de la FACTURA como plantilla.**"
            )
            st.dataframe(pd.DataFrame(filas_fac), use_container_width=True, height=260)
            servicios_visuales = usuario_fac.get("servicios", {}) if usuario_fac else {}
        else:
            st.info("Este usuario no tiene servicios en el JSON de la NOTA.")
            servicios_visuales = usuario_nota.get("servicios", {}) or {}

        # Editor JSON de servicios (lo que se guarde va a la NOTA)
        servicios_str = json.dumps(servicios_visuales, ensure_ascii=False, indent=2)
        ayuda_servicios = (
            "Edite el JSON de `servicios` que se guardará en la **NOTA** para este usuario.\n"
            "- Si lo que ve proviene de la FACTURA, al guardar se copiará esa estructura a la NOTA.\n"
        )
        servicios_editados = st.text_area(
            ayuda_servicios,
            value=servicios_str,
            height=260,
            key=f"servicios_usuario_{idx_sel}",
        )

        if st.button("Guardar SOLO servicios en este usuario (NOTA)"):
            try:
                servicios_nuevos = json.loads(servicios_editados)
            except json.JSONDecodeError as exc:
                st.error(f"El JSON de servicios no es válido: {exc}")
            else:
                usuario_nota["servicios"] = servicios_nuevos
                normalizar_servicios_usuario(usuario_nota)
                usuarios_nota[idx_sel] = usuario_nota
                nota_data["usuarios"] = usuarios_nota
                st.session_state["nota_data"] = nota_data
                st.success("Servicios actualizados correctamente en el JSON de la NOTA para este usuario.")

        # Editor avanzado: usuario completo
        with st.expander("⚙️ Edición avanzada: usuario completo (demográficos + servicios)", expanded=False):
            usuario_str = json.dumps(usuario_nota, ensure_ascii=False, indent=2)
            usuario_editado = st.text_area(
                "JSON completo del usuario (se guardará tal cual en la NOTA).",
                value=usuario_str,
                height=260,
                key=f"usuario_completo_{idx_sel}",
            )
            if st.button("Guardar usuario completo (NOTA)", key=f"btn_usuario_completo_{idx_sel}"):
                try:
                    nuevo_usuario = json.loads(usuario_editado)
                except json.JSONDecodeError as exc:
                    st.error(f"El JSON del usuario no es válido: {exc}")
                else:
                    if not isinstance(nuevo_usuario, dict):
                        st.error("El JSON del usuario debe ser un objeto/dict.")
                    else:
                        normalizar_servicios_usuario(nuevo_usuario)
                        usuarios_nota[idx_sel] = nuevo_usuario
                        nota_data["usuarios"] = usuarios_nota
                        st.session_state["nota_data"] = nota_data
                        st.success("Usuario completo actualizado correctamente en la NOTA.")

    # ---- 6. Edición masiva con plantilla ----
    st.markdown("---")
    st.subheader("6️⃣ Edición masiva con plantilla (demográficos + valor de la nota por servicio)")

    campos_paciente_txt = "`, `".join(CAMPOS_PACIENTE)

    st.markdown(
        f"""
        **Plantilla (xlsx/csv):**

        - Cada fila = un servicio de un usuario.
        - Incluye campos demográficos del paciente (a nivel de usuario) y datos del servicio.
        - Campos clave mínimos:
          - `idx_usuario`: índice del usuario en `nota['usuarios']`.
          - `tipo_servicio`: (ej. `consultas`, `procedimientos`).
          - `idx_item`: posición del servicio en la lista de ese tipo.
          - `vrServicio_factura`: valor en la factura (referencia, si hay factura).
          - `vrServicio_nota`: valor que tendrá el servicio en la NOTA (este lo diligencia usted).
          - `campos_faltantes_nota`: campos del servicio que están vacíos/None en la nota.
        - Además, puede corregir masivamente los campos del paciente:
          - `{campos_paciente_txt}`
        - Solo se aplican cambios de servicio en filas donde `vrServicio_nota` tenga un valor.
        """
    )

    col_descarga, col_subida = st.columns(2)

    with col_descarga:
        buffer, ext, mime = generar_plantilla_servicios(
            nota_data,
            factura_data if usar_factura else None,
        )
        st.download_button(
            "⬇️ Descargar plantilla de servicios (Excel si es posible, si no CSV)",
            data=buffer,
            file_name=f"plantilla_servicios_rips.{ext}",
            mime=mime,
        )

    with col_subida:
        if plantilla_file is not None:
            if st.button("Aplicar cambios desde plantilla"):
                nota_actualizada, errores = aplicar_plantilla_servicios(
                    nota_data,
                    factura_data if usar_factura else None,
                    plantilla_file,
                )
                nota_actualizada = normalizar_documento_servicios(nota_actualizada)
                st.session_state["nota_data"] = nota_actualizada
                nota_data = nota_actualizada
                if errores:
                    st.warning("Se aplicaron los cambios, pero hubo advertencias:")
                    for e in errores:
                        st.write(f"- {e}")
                else:
                    st.success("Cambios masivos aplicados correctamente desde la plantilla.")

    # ---- 7. Descarga completa ----
    st.markdown("---")
    st.subheader("7️⃣ Descargar JSON y XML de la nota completa")

    nota_json_bytes = json.dumps(nota_data, ensure_ascii=False, indent=2).encode("utf-8")
    nombre_nota_base = st.session_state.get("nota_name") or "nota_corregida"

    col_json, col_xml = st.columns(2)
    with col_json:
        st.download_button(
            "⬇️ Descargar JSON corregido (NOTA completa)",
            data=nota_json_bytes,
            file_name=f"{nombre_nota_base.rsplit('.', 1)[0]}_corregida.json",
            mime="application/json",
        )

    with col_xml:
        xml_bytes = nota_json_a_xml_bytes(nota_data)
        st.download_button(
            "⬇️ Descargar XML generado desde JSON de la nota (completa)",
            data=xml_bytes,
            file_name=f"{nombre_nota_base.rsplit('.', 1)[0]}.xml",
            mime="application/xml",
        )

    # ---- 8. Solo usuarios que estaban incompletos y ahora ya tienen servicios ----
    st.markdown("---")
    st.subheader("8️⃣ Descargar SOLO usuarios que estaban incompletos y ya están completos")

    orig_incompletos = st.session_state.get("usuarios_incompletos_original", [])
    if not orig_incompletos:
        st.info(
            "No se registraron usuarios incompletos en la nota original, "
            "o la nota se cargó después de que ya estuviera corregida."
        )
    else:
        usuarios_actuales = nota_data.get("usuarios", []) or []
        indices_completos = []
        for idx in orig_incompletos:
            if 0 <= idx < len(usuarios_actuales):
                u = usuarios_actuales[idx]
                if tiene_lista_con_items(u.get("servicios")):
                    indices_completos.append(idx)

        if not indices_completos:
            st.info(
                "Ninguno de los usuarios que estaba incompleto en la nota original "
                "tiene servicios completos aún."
            )
        else:
            filas = []
            for idx in indices_completos:
                u = usuarios_actuales[idx]
                filas.append(
                    {
                        "idx": idx,
                        "tipoDocumentoIdentificacion": u.get("tipoDocumentoIdentificacion"),
                        "numDocumentoIdentificacion": u.get("numDocumentoIdentificacion"),
                    }
                )
            st.markdown("**Usuarios incluidos en la exportación filtrada:**")
            st.dataframe(pd.DataFrame(filas), use_container_width=True, height=200)

            nota_filtrada = {k: v for k, v in nota_data.items() if k != "usuarios"}
            nota_filtrada["usuarios"] = [usuarios_actuales[i] for i in indices_completos]

            json_filtrado_bytes = json.dumps(
                nota_filtrada, ensure_ascii=False, indent=2
            ).encode("utf-8")

            col_json_f, col_xml_f = st.columns(2)
            with col_json_f:
                st.download_button(
                    "⬇️ Descargar JSON (solo usuarios completados)",
                    data=json_filtrado_bytes,
                    file_name=f"{nombre_nota_base.rsplit('.', 1)[0]}_solo_usuarios_completados.json",
                    mime="application/json",
                )
            with col_xml_f:
                xml_filtrado_bytes = nota_json_a_xml_bytes(nota_filtrada)
                st.download_button(
                    "⬇️ Descargar XML (solo usuarios completados)",
                    data=xml_filtrado_bytes,
                    file_name=f"{nombre_nota_base.rsplit('.', 1)[0]}_solo_usuarios_completados.xml",
                    mime="application/xml",
                )


if __name__ == "__main__":
    main()
