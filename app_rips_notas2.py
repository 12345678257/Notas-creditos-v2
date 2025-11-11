# app_rips_notas.py
import json
import copy
import re
from io import BytesIO
from typing import Dict, Any, List, Tuple, Optional

import pandas as pd
import streamlit as st
import xml.etree.ElementTree as ET
from xml.dom import minidom


# ==========================
# Constantes de negocio
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

CODIGOS_LONGITUD = {
    "tipoUsuario": 2,
    "codPaisResidencia": 3,
    "codPaisOrigen": 3,
    "codMunicipioResidencia": 5,
    "codZonaTerritorialResidencia": 2,
}


# ==========================
# Utilidades
# ==========================

def _is_dict(x): return isinstance(x, dict)
def _is_list(x): return isinstance(x, list)

def tiene_lista_con_items(servicios: Any) -> bool:
    if not isinstance(servicios, dict):
        return False
    for v in servicios.values():
        if isinstance(v, list) and len(v) > 0:
            return True
    return False

def ajustar_signo_servicios(servicios: Dict[str, Any], signo: int) -> None:
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
    serv = usuario.get("servicios")
    if not isinstance(serv, dict):
        serv = {}
    for grupo in SERVICIO_GRUPOS:
        if not isinstance(serv.get(grupo), list):
            serv[grupo] = []
    usuario["servicios"] = serv

def normalizar_documento_servicios(doc: Dict[str, Any]) -> Dict[str, Any]:
    usuarios = doc.get("usuarios")
    if not isinstance(usuarios, list):
        return doc
    for u in usuarios:
        if isinstance(u, dict):
            normalizar_servicios_usuario(u)
    doc["usuarios"] = usuarios
    return doc

def formatear_codigo_campo(campo: str, valor: Any) -> str:
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
    usuarios = nota.get("usuarios", [])
    if not isinstance(usuarios, list):
        return nota
    for u in usuarios:
        if not isinstance(u, dict):
            continue
        u["tipoUsuario"] = "08"  # solicitado por ti
        for campo in ("codPaisResidencia", "codPaisOrigen",
                      "codMunicipioResidencia", "codZonaTerritorialResidencia"):
            if campo in u and u[campo] not in (None, ""):
                u[campo] = formatear_codigo_campo(campo, u[campo])
        if "fechaNacimiento" in u and u["fechaNacimiento"]:
            u["fechaNacimiento"] = str(u["fechaNacimiento"])[:10]
        if "consecutivo" in u and u["consecutivo"] not in (None, ""):
            try:
                u["consecutivo"] = int(u["consecutivo"])
            except Exception:
                pass
    nota["usuarios"] = usuarios
    return nota

def copiar_servicios_factura_a_nota(
    factura: Dict[str, Any],
    nota: Dict[str, Any],
    forzar_signo: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    inv_users = factura.get("usuarios", [])
    note_users = nota.get("usuarios", [])

    inv_map_full = {}
    inv_map_by_num = {}
    for u in inv_users:
        if not _is_dict(u): continue
        tipo = u.get("tipoDocumentoIdentificacion")
        num = u.get("numDocumentoIdentificacion")
        if num:
            if tipo:
                inv_map_full[(tipo, num)] = u
            inv_map_by_num[num] = u

    usuarios_modificados = 0
    usuarios_ya_tenian_servicios = 0
    usuarios_demografia_completada = 0
    usuarios_sin_encontrar = []

    for u in note_users:
        if not _is_dict(u): continue
        tipo = u.get("tipoDocumentoIdentificacion")
        num = u.get("numDocumentoIdentificacion")
        u_fact = inv_map_full.get((tipo, num)) or inv_map_by_num.get(num or "")
        if u_fact is None:
            usuarios_sin_encontrar.append((tipo, num))
            continue

        # copiar demográficos desde factura (y normalizar)
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

        # normalizar estructuras
        normalizar_servicios_usuario(u_fact)
        normalizar_servicios_usuario(u)

        if tiene_lista_con_items(u.get("servicios")):
            usuarios_ya_tenian_servicios += 1
            continue

        nuevo_servicios = copy.deepcopy(u_fact.get("servicios", {}))
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

def obtener_claves_servicio_esperadas(factura: Optional[Dict[str, Any]], nota: Optional[Dict[str, Any]]) -> List[str]:
    mejor_keys = set(); mejor_len = 0
    for doc in (factura, nota):
        if not doc: continue
        for u in doc.get("usuarios", []):
            sv = u.get("servicios", {})
            if not _is_dict(sv): continue
            for lst in sv.values():
                if not _is_list(lst): continue
                for it in lst:
                    if _is_dict(it):
                        ks = set(it.keys())
                        if len(ks) > mejor_len:
                            mejor_len = len(ks); mejor_keys = ks
    return sorted(mejor_keys)

def desglosar_servicios_usuario(usuario: Optional[Dict[str, Any]], claves_esperadas: List[str]) -> List[Dict[str, Any]]:
    filas = []
    if not usuario: return filas
    servicios = usuario.get("servicios") or {}
    if not _is_dict(servicios): return filas
    for tipo, lst in servicios.items():
        if not _is_list(lst): continue
        for i, item in enumerate(lst):
            fila = {"tipo_servicio": tipo, "idx_item": i}
            faltantes = []
            for k in claves_esperadas:
                v = item.get(k) if _is_dict(item) else None
                fila[k] = v
                if v in (None, ""): faltantes.append(k)
            fila["campos_faltantes"] = ",".join(faltantes)
            filas.append(fila)
    return filas

def generar_resumen_usuarios(nota: Dict[str, Any]) -> pd.DataFrame:
    filas = []
    for i, u in enumerate(nota.get("usuarios", [])):
        sv = u.get("servicios", {})
        ok = tiene_lista_con_items(sv)
        num_listas = sum(1 for v in sv.values() if isinstance(v, list))
        total_items = sum(len(v) for v in sv.values() if isinstance(v, list))
        filas.append({
            "idx": i,
            "tipoDocumentoIdentificacion": u.get("tipoDocumentoIdentificacion"),
            "numDocumentoIdentificacion": u.get("numDocumentoIdentificacion"),
            "estadoServicios": "OK" if ok else "INCOMPLETO",
            "numListasServicios": num_listas,
            "totalItemsServicios": total_items,
        })
    return pd.DataFrame(filas)

def generar_plantilla_servicios(nota: Dict[str, Any], factura: Optional[Dict[str, Any]]) -> Tuple[BytesIO, str, str]:
    claves = obtener_claves_servicio_esperadas(factura, nota)
    filas = []

    usuarios_nota = nota.get("usuarios", []) or []
    usuarios_fac = factura.get("usuarios", []) if factura else []

    for idx_u in range(len(usuarios_nota)):
        u_nota = usuarios_nota[idx_u]
        u_fac = usuarios_fac[idx_u] if 0 <= idx_u < len(usuarios_fac) else None

        filas_nota = desglosar_servicios_usuario(u_nota, claves)
        filas_fac = desglosar_servicios_usuario(u_fac, claves) if u_fac else []

        map_fac = {(f["tipo_servicio"], f["idx_item"]): f for f in filas_fac}

        def agrega_paciente(base: Dict[str, Any]):
            for campo in CAMPOS_PACIENTE:
                base[campo] = u_nota.get(campo) if u_nota and campo in u_nota \
                    else (u_fac.get(campo) if u_fac and campo in u_fac else None)

        if filas_nota:
            for f in filas_nota:
                basef = map_fac.get((f["tipo_servicio"], f["idx_item"]), {})
                fila = {
                    "idx_usuario": idx_u,
                    "tipo_servicio": f["tipo_servicio"],
                    "idx_item": f["idx_item"],
                    "vrServicio_factura": basef.get("vrServicio"),
                    "vrServicio_nota": f.get("vrServicio"),
                    "campos_faltantes_nota": f.get("campos_faltantes", ""),
                }
                agrega_paciente(fila)
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
                agrega_paciente(fila)
                filas.append(fila)

    df = pd.DataFrame(filas)
    buffer = BytesIO(); ext = "xlsx"; mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    try:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="servicios")
    except Exception:
        buffer = BytesIO()
        df.to_csv(buffer, index=False)
        ext = "csv"; mime = "text/csv"
    buffer.seek(0)
    return buffer, ext, mime

def aplicar_plantilla_servicios(nota: Dict[str, Any], factura: Optional[Dict[str, Any]], archivo) -> Tuple[Dict[str, Any], List[str]]:
    errores = []
    try:
        nombre = getattr(archivo, "name", "") or ""
        if nombre.lower().endswith(".csv"):
            df = pd.read_csv(archivo)
        else:
            df = pd.read_excel(archivo)
    except Exception as exc:
        errores.append(f"No se pudo leer la plantilla: {exc}")
        return nota, errores

    obligatorias = ["idx_usuario", "tipo_servicio", "idx_item", "vrServicio_nota"]
    for col in obligatorias:
        if col not in df.columns:
            errores.append(f"Falta columna '{col}' en la plantilla.")
            return nota, errores

    usuarios_nota = nota.get("usuarios", [])
    usuarios_fac = factura.get("usuarios", []) if factura else []

    updated_indices = set(st.session_state.get("usuarios_actualizados_desde_excel", []))

    for _, fila in df.iterrows():
        try: idx_u = int(fila["idx_usuario"])
        except Exception:
            errores.append(f"Índice de usuario inválido: {fila.get('idx_usuario')}")
            continue
        tipo_serv = str(fila["tipo_servicio"])
        try: idx_item = int(fila["idx_item"])
        except Exception:
            errores.append(f"Ítem inválido para usuario {idx_u}: {fila.get('idx_item')}")
            continue
        vr = fila["vrServicio_nota"]
        if pd.isna(vr):  # si no diligenciaron, omitir
            continue
        if not (0 <= idx_u < len(usuarios_nota)):
            errores.append(f"Usuario {idx_u} fuera de rango.")
            continue

        u_nota = usuarios_nota[idx_u]

        # actualizar demográficos si vienen en la plantilla (tipoUsuario forzado "08")
        for campo in CAMPOS_PACIENTE:
            if campo not in df.columns: continue
            val = fila[campo]
            if pd.isna(val): continue
            if campo == "tipoUsuario":
                u_nota[campo] = "08"
            elif campo == "consecutivo":
                try: u_nota[campo] = int(val)
                except Exception: u_nota[campo] = val
            elif campo == "fechaNacimiento":
                u_nota[campo] = str(val)[:10]
            elif campo in CODIGOS_LONGITUD:
                u_nota[campo] = formatear_codigo_campo(campo, val)
            else:
                if isinstance(val, float) and val.is_integer(): val = int(val)
                u_nota[campo] = str(val)

        sv_nota = u_nota.get("servicios")
        if not isinstance(sv_nota, dict):
            sv_nota = {}; u_nota["servicios"] = sv_nota
        lista = sv_nota.get(tipo_serv)

        # Si la estructura no está, intentar copiar de factura
        if not (isinstance(lista, list) and idx_item < len(lista)):
            if not factura:
                errores.append(f"No existe estructura para {tipo_serv}[{idx_item}] y no hay factura.")
                usuarios_nota[idx_u] = u_nota; continue
            u_fac = None
            if "tipoDocumentoIdentificacion" in df.columns and "numDocumentoIdentificacion" in df.columns:
                t = fila["tipoDocumentoIdentificacion"]; n = fila["numDocumentoIdentificacion"]
                if not pd.isna(t) and not pd.isna(n):
                    t = str(t); n = str(int(n)) if (isinstance(n, float) and n.is_integer()) else str(n)
                    for uf in usuarios_fac:
                        if _is_dict(uf) and uf.get("tipoDocumentoIdentificacion") == t and str(uf.get("numDocumentoIdentificacion")) == n:
                            u_fac = uf; break
            if u_fac is None:
                if not (0 <= idx_u < len(usuarios_fac)):
                    errores.append(f"No se encontró usuario {idx_u} en factura para crear estructura.")
                    usuarios_nota[idx_u] = u_nota; continue
                u_fac = usuarios_fac[idx_u]

            sv_fac = u_fac.get("servicios", {})
            lista_fac = sv_fac.get(tipo_serv)
            if not (isinstance(lista_fac, list) and idx_item < len(lista_fac)):
                errores.append(f"No hay línea base en factura para {tipo_serv}[{idx_item}].")
                usuarios_nota[idx_u] = u_nota; continue

            item_base = copy.deepcopy(lista_fac[idx_item])
            if not isinstance(lista, list): lista = []
            while len(lista) <= idx_item: lista.append({})
            lista[idx_item] = item_base
            sv_nota[tipo_serv] = lista

        lista = sv_nota.get(tipo_serv, [])
        if not (isinstance(lista, list) and idx_item < len(lista)):
            errores.append(f"No se pudo asegurar {tipo_serv}[{idx_item}] en la nota.")
            usuarios_nota[idx_u] = u_nota; continue

        try: valor = float(vr)
        except Exception:
            errores.append(f"vrServicio_nota inválido en {tipo_serv}[{idx_item}]: {vr}")
            usuarios_nota[idx_u] = u_nota; continue

        item = lista[idx_item]
        item["vrServicio"] = valor
        lista[idx_item] = item
        sv_nota[tipo_serv] = lista
        u_nota["servicios"] = sv_nota
        usuarios_nota[idx_u] = u_nota
        updated_indices.add(idx_u)

    nota["usuarios"] = usuarios_nota
    nota = normalizar_codigos_usuarios(nota)
    st.session_state["usuarios_actualizados_desde_excel"] = sorted(list(updated_indices))
    return nota, errores


# ==========================
# RipsDocumento XML (a partir del JSON de la nota)
# ==========================

def rips_nota_json_a_xml_element(nota: Dict[str, Any]) -> ET.Element:
    root = ET.Element("RipsDocumento")
    for key, val in nota.items():
        if key == "usuarios":
            continue
        child = ET.SubElement(root, key)
        child.text = "" if val is None else str(val)

    usuarios_el = ET.SubElement(root, "usuarios")
    for u in nota.get("usuarios", []):
        u_el = ET.SubElement(usuarios_el, "usuario")
        for k, v in u.items():
            if k == "servicios":
                serv_el = ET.SubElement(u_el, "servicios")
                if isinstance(v, dict):
                    for tipo, lst in v.items():
                        t_el = ET.SubElement(serv_el, str(tipo))
                        if isinstance(lst, list):
                            for item in lst:
                                it_el = ET.SubElement(t_el, "item")
                                if isinstance(item, dict):
                                    for kk, vv in item.items():
                                        c = ET.SubElement(it_el, str(kk))
                                        c.text = "" if vv is None else str(vv)
                continue
            c = ET.SubElement(u_el, str(k))
            c.text = "" if v is None else str(v)
    return root

def rips_nota_json_a_xml_string(nota: Dict[str, Any]) -> str:
    elem = rips_nota_json_a_xml_element(nota)
    rough = ET.tostring(elem, encoding="utf-8")
    dom = minidom.parseString(rough)
    pretty = dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
    # incluir encabezado xml como en tu ejemplo
    if not pretty.strip().startswith("<?xml"):
        pretty = '<?xml version="1.0" encoding="utf-8" standalone="no"?>\n' + pretty
    return pretty

def incrustar_rips_en_attacheddocument(xml_template_bytes: bytes, rips_xml_text: str) -> bytes:
    """
    Reemplaza el PRIMER bloque CDATA dentro de:
    <cac:Attachment>/<cac:ExternalReference>/<cbc:Description><![CDATA[ ... ]]></cbc:Description>
    por el RipsDocumento generado.
    """
    xml_txt = xml_template_bytes.decode("utf-8", errors="ignore")

    # buscamos el primer Description con CDATA
    ini = xml_txt.find("<cbc:Description><![CDATA[")
    if ini == -1:
        raise ValueError("No se encontró '<cbc:Description><![CDATA[' en la plantilla.")
    ini_c = ini + len("<cbc:Description><![CDATA[")
    fin = xml_txt.find("]]></cbc:Description>", ini_c)
    if fin == -1:
        raise ValueError("No se encontró cierre ']]></cbc:Description>' en la plantilla.")

    # reemplazo directo del CDATA
    nuevo = xml_txt[:ini_c] + rips_xml_text + xml_txt[fin:]
    return nuevo.encode("utf-8")


# ==========================
# Helpers de sesión / carga
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
    st.set_page_config(page_title="RIPS Notas & AttachedDocument UBL", layout="wide")
    st.title("🧾 RIPS Notas & AttachedDocument UBL")

    st.sidebar.header("1️⃣ Cargar archivos")
    factura_file = st.sidebar.file_uploader("JSON FACTURA (referencia, completo)", type=["json"])
    nota_file    = st.sidebar.file_uploader("JSON NOTA (a corregir / NC)", type=["json"])
    plantilla_file = st.sidebar.file_uploader("Plantilla masiva (xlsx o csv)", type=["xlsx","csv"])
    xml_tpl_file = st.sidebar.file_uploader("XML plantilla AttachedDocument (opcional)", type=["xml"])

    # Estado
    if "factura_data" not in st.session_state:
        st.session_state["factura_data"] = None; st.session_state["factura_name"] = None
    if "nota_data" not in st.session_state:
        st.session_state["nota_data"] = None; st.session_state["nota_name"] = None

    cargar_json_en_estado(factura_file, "factura_data", "factura_name")
    cargar_json_en_estado(nota_file, "nota_data", "nota_name")

    factura = obtener_factura()
    nota = obtener_nota()

    # Normalizaciones
    if factura:
        factura = normalizar_documento_servicios(factura)
        st.session_state["factura_data"] = factura
    if nota:
        nota = normalizar_documento_servicios(nota)
        nota = normalizar_codigos_usuarios(nota)
        st.session_state["nota_data"] = nota

    factura = obtener_factura(); nota = obtener_nota()
    if not nota:
        st.info("Sube, al menos, el JSON de la NOTA para trabajar.")
        st.stop()

    st.markdown("### 2️⃣ Encabezados")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Factura (referencia)**")
        if factura:
            st.json({
                "numDocumentoIdObligado": factura.get("numDocumentoIdObligado"),
                "numFactura": factura.get("numFactura"),
                "tipoNota": factura.get("tipoNota"),
                "numNota": factura.get("numNota"),
                "usuarios": len(factura.get("usuarios", [])),
            })
        else:
            st.info("Opcional.")
    with c2:
        st.markdown("**Nota (objetivo)**")
        st.json({
            "numDocumentoIdObligado": nota.get("numDocumentoIdObligado"),
            "numFactura": nota.get("numFactura"),
            "tipoNota": nota.get("tipoNota"),
            "numNota": nota.get("numNota"),
            "usuarios": len(nota.get("usuarios", [])),
        })

    # 3) Completar desde factura
    st.markdown("---")
    st.subheader("3️⃣ Completar datos/servicios de la NOTA desde la FACTURA (opcional)")
    if factura:
        col_a, col_b = st.columns([2,1])
        with col_a:
            opt = st.selectbox("Signo para valores de servicios copiados:", ("Dejar igual", "Forzar POSITIVOS", "Forzar NEGATIVOS"))
            signo = None
            if opt == "Forzar POSITIVOS": signo = 1
            if opt == "Forzar NEGATIVOS": signo = -1
        with col_b:
            if st.button("Rellenar servicios vacíos y demográficos desde factura"):
                nota2, res = copiar_servicios_factura_a_nota(factura, copy.deepcopy(nota), signo)
                nota2 = normalizar_documento_servicios(nota2); nota2 = normalizar_codigos_usuarios(nota2)
                st.session_state["nota_data"] = nota2; nota = nota2
                st.success(
                    f"Usuarios con servicios copiados: {res['usuarios_modificados']} | "
                    f"Demográficos completados: {res['usuarios_demografia_completada']} | "
                    f"Ya tenían servicios: {res['usuarios_ya_tenian_servicios']} | "
                    f"Sin coincidencia en factura: {len(res['usuarios_sin_encontrar'])}"
                )
    else:
        st.info("Carga la factura si quieres usarla como referencia para completar la nota.")

    # 4) Resumen
    st.markdown("---")
    st.subheader("4️⃣ Resumen de usuarios en NOTA")
    df_resumen = generar_resumen_usuarios(nota)
    st.dataframe(df_resumen, use_container_width=True, height=300)

    # 5) Plantilla masiva
    st.markdown("---")
    st.subheader("5️⃣ Edición masiva (xlsx/csv)")
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        buf, ext, mime = generar_plantilla_servicios(nota, factura)
        st.download_button("⬇️ Descargar plantilla", data=buf, file_name=f"plantilla_servicios.{ext}", mime=mime)
    with col_p2:
        if plantilla_file is not None and st.button("Aplicar cambios desde plantilla"):
            nota3, errs = aplicar_plantilla_servicios(nota, factura, plantilla_file)
            nota3 = normalizar_documento_servicios(nota3); nota3 = normalizar_codigos_usuarios(nota3)
            st.session_state["nota_data"] = nota3; nota = nota3
            if errs:
                st.warning("Se aplicó la plantilla con observaciones:")
                for e in errs: st.write("- ", e)
            else:
                st.success("Plantilla aplicada sin observaciones.")

    # 6) Export JSON / XML (RipsDocumento)
    st.markdown("---")
    st.subheader("6️⃣ Exportar JSON/XML (RipsDocumento) de la NOTA completa")
    nota = normalizar_codigos_usuarios(nota)
    json_bytes = json.dumps(nota, ensure_ascii=False, indent=2).encode("utf-8")
    xml_rips_text = rips_nota_json_a_xml_string(nota)
    xml_rips_bytes = xml_rips_text.encode("utf-8")

    col_e1, col_e2 = st.columns(2)
    with col_e1:
        st.download_button("⬇️ JSON Nota (completa)", data=json_bytes, file_name="nota_corregida.json", mime="application/json")
    with col_e2:
        st.download_button("⬇️ XML RipsDocumento (completo)", data=xml_rips_bytes, file_name="RipsDocumento.xml", mime="application/xml")

    # 7) Solo usuarios con nota aplicada (desde Excel o selección)
    st.markdown("---")
    st.subheader("7️⃣ Exportar SOLO usuarios con nota aplicada")
    updated = set(st.session_state.get("usuarios_actualizados_desde_excel", []))
    usuarios = nota.get("usuarios", []) or []
    # construir opciones visibles
    opciones = {f"{i} - {u.get('tipoDocumentoIdentificacion','')} {u.get('numDocumentoIdentificacion','')}": i
                for i, u in enumerate(usuarios) if i in updated and tiene_lista_con_items(u.get("servicios"))}

    if not opciones:
        st.info("No hay usuarios marcados como actualizados desde Excel. (Aplica plantilla en la sección 5).")
    else:
        st.write("Usuarios actualizados (Excel):")
        st.dataframe(pd.DataFrame(
            [{"idx": i,
              "tipoDocumentoIdentificacion": usuarios[i].get("tipoDocumentoIdentificacion"),
              "numDocumentoIdentificacion": usuarios[i].get("numDocumentoIdentificacion")} for i in sorted(opciones.values())]
        ), use_container_width=True, height=180)

        # exportar todos
        base = {k: v for k, v in nota.items() if k != "usuarios"}
        nota_todos = copy.deepcopy(base); nota_todos["usuarios"] = [usuarios[i] for i in sorted(opciones.values())]
        nota_todos = normalizar_codigos_usuarios(nota_todos)

        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.download_button("⬇️ JSON (solo actualizados)", data=json.dumps(nota_todos, ensure_ascii=False, indent=2).encode("utf-8"),
                               file_name="nota_solo_actualizados.json", mime="application/json")
        with col_t2:
            xml_txt = rips_nota_json_a_xml_string(nota_todos)
            st.download_button("⬇️ XML RipsDocumento (solo actualizados)", data=xml_txt.encode("utf-8"),
                               file_name="RipsDocumento_solo_actualizados.xml", mime="application/xml")

        # selección parcial
        st.markdown("**(Opcional) Exportar un subconjunto**")
        seleccion = st.multiselect("Elige usuarios:", list(opciones.keys()))
        if seleccion:
            idxs = [opciones[s] for s in seleccion]
            nota_sel = copy.deepcopy(base); nota_sel["usuarios"] = [usuarios[i] for i in idxs]
            nota_sel = normalizar_codigos_usuarios(nota_sel)
            col_s1, col_s2 = st.columns(2)
            with col_s1:
                st.download_button("⬇️ JSON (seleccionados)", data=json.dumps(nota_sel, ensure_ascii=False, indent=2).encode("utf-8"),
                                   file_name="nota_seleccionados.json", mime="application/json")
            with col_s2:
                xml_txt = rips_nota_json_a_xml_string(nota_sel)
                st.download_button("⬇️ XML RipsDocumento (seleccionados)", data=xml_txt.encode("utf-8"),
                                   file_name="RipsDocumento_seleccionados.xml", mime="application/xml")

    # 8) AttachedDocument UBL (incrustar RIPS en plantilla)
    st.markdown("---")
    st.subheader("8️⃣ Generar **AttachedDocument** UBL con el RIPS embebido (usando tu plantilla)")
    st.write(
        "Sube un XML plantilla **AttachedDocument** (como el que compartiste). "
        "La app reemplaza el **primer** CDATA en `<cac:Attachment>/<cac:ExternalReference>/<cbc:Description>` "
        "por el **RipsDocumento** generado, sin tocar encabezados, namespaces ni firmas."
    )
    st.caption("Si tu plantilla tiene varios `<cbc:Description>`, se reemplaza el primero (ubicado usualmente en el contenedor principal).")

    col_a1, col_a2 = st.columns(2)
    with col_a1:
        target = st.selectbox("¿Qué quieres incrustar en el AttachedDocument?", ("RIPS de la NOTA completa", "RIPS solo usuarios actualizados (Excel)"))
    with col_a2:
        if xml_tpl_file is not None and st.button("⬇️ Generar AttachedDocument con RIPS embebido"):
            # preparar RIPS según selección
            if target == "RIPS solo usuarios actualizados (Excel)":
                updated = set(st.session_state.get("usuarios_actualizados_desde_excel", []))
                base = {k: v for k, v in nota.items() if k != "usuarios"}
                sel = [u for i, u in enumerate(nota.get("usuarios", [])) if i in updated]
                if not sel:
                    st.error("No hay usuarios marcados como actualizados desde Excel.")
                    st.stop()
                nota_base = copy.deepcopy(base); nota_base["usuarios"] = sel
            else:
                nota_base = copy.deepcopy(nota)

            nota_base = normalizar_codigos_usuarios(nota_base)
            rips_text = rips_nota_json_a_xml_string(nota_base)
            try:
                tpl_bytes = xml_tpl_file.read()
                attached = incrustar_rips_en_attacheddocument(tpl_bytes, rips_text)
            except Exception as exc:
                st.error(f"No se pudo incrustar el RIPS en la plantilla: {exc}")
            else:
                st.download_button(
                    "⬇️ Descargar AttachedDocument UBL con RIPS",
                    data=attached,
                    file_name="AttachedDocument_RIPS.xml",
                    mime="application/xml",
                )


if __name__ == "__main__":
    main()
