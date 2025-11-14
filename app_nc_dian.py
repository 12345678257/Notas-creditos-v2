# -*- coding: utf-8 -*-
# app_nc_dian.py
#
# Requisitos:
#   pip install streamlit pandas lxml openpyxl xlsxwriter
#
# Ejecutar local:
#   streamlit run app_nc_dian.py
#
# Funcionalidad:
# - Carga RipsDocumento JSON (nota crédito) y extrae solo servicios con valor.
# - Tabla editable + plantilla Excel para editar valor de la nota (individual/masivo).
# - Genera JSON Afacturar/TTP (nota crédito).
# - Reutiliza un AttachedDocument DIAN de PLANTILLA (válido) y solo reemplaza datos mínimos.
# - Modo “1 línea = total” o “1 línea por servicio” en el CreditNote interno.
#
from __future__ import annotations
import io
import json
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import streamlit as st
from lxml import etree


# ---------------------- Utilidades numéricas/JSON ----------------------

def _dec(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    if v is None or v == "":
        return Decimal("0.00")
    return Decimal(str(v))


def _fmt2(v) -> str:
    """Formatea con 2 decimales, separador punto."""
    return str(_dec(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _load_json_bytes(data: bytes) -> Dict[str, Any]:
    return json.loads(data.decode("utf-8"))


# ---------------------- Extracción de servicios con valor ----------------------

def extraer_servicios_con_valor(rips: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Recorre usuarios -> servicios -> listas y recoge los registros con vrServicio > 0.
    Devuelve filas con identificadores útiles para selección/edición.
    """
    filas: List[Dict[str, Any]] = []
    usuarios = rips.get("usuarios", [])
    for u_idx, u in enumerate(usuarios):
        paciente = str(u.get("numDocumentoIdentificacion", "")) or ""
        servicios = u.get("servicios") or {}
        for tabla, regs in servicios.items():
            if not isinstance(regs, list):
                continue
            for s_idx, reg in enumerate(regs):
                vr = _dec(reg.get("vrServicio", 0))
                if vr > 0:
                    filas.append({
                        "incluir": True,
                        "paciente": paciente,
                        "tabla": tabla,
                        "u_idx": u_idx,
                        "s_idx": s_idx,
                        "codPrestador": reg.get("codPrestador", ""),
                        "codConsulta": reg.get("codConsulta", ""),
                        "codProcedimiento": reg.get("codProcedimiento", ""),
                        "codServicio": reg.get("codServicio", ""),
                        "fechaInicioAtencion": reg.get("fechaInicioAtencion", ""),
                        "valor_original": float(vr),
                        "valor_nc": float(vr),  # editable
                    })
    return filas


# ---------------------- Construcción JSON Afacturar/TTP ----------------------

def construir_payload_afacturar_ttp(
    rips: Dict[str, Any],
    filas_df: pd.DataFrame,
    *,
    id_nc: str,
    ref_doc: str,
    cude_ref: str,
    doc_obligado: str,
    moneda: str = "COP",
    tipo_operacion: str = "35",
    tipo_nc: str = "4",
    prefijo: str = "NC",
) -> Dict[str, Any]:
    """
    Construye el payload JSON para el endpoint TTP/nota_credito con:
    - Solo filas marcadas como incluir=True
    - Valores vrServicio tomados de 'valor_nc' (editado)
    - Totales consistentes (sin impuestos/retenciones)
    """
    sel = filas_df[filas_df["incluir"] == True].copy()  # noqa: E712
    if sel.empty:
        raise ValueError("No hay ítems seleccionados para la nota crédito.")

    detalle = []
    total = Decimal("0.00")
    for i, row in enumerate(sel.itertuples(index=False), start=1):
        valor = _fmt2(row.valor_nc)
        total += _dec(row.valor_nc)
        paciente = str(row.paciente)

        detalle.append({
            "numero_linea": i,
            "cantidad": 1,
            "unidad_de_cantidad": "94",
            "valor_unitario": valor,
            "descripcion": "Servicio sector salud",
            "nota_detalle": f"Ajuste parcial - Paciente {paciente}",
            "marca": "N/A",
            "modelo": "N/A",
            "codificacion_estandar": {
                "cod_grupo_bien_servicio": "1",
                "nombre_grupo_bien_servicio": "UNSPSC",
                "cod_segmento_bien_servicio": "7811",
                "cod_bien_servicio": "78111000",
            },
            "regalo": {
                "es_regalo": False,
                "cod_precio_referencia": "0",
                "precio_referencia": "0.00",
            },
            "cargo_descuento": {
                "es_descuento": True,
                "porcentaje_cargo_descuento": "0.00",
                "valor_base_cargo_descuento": "0.00",
                "valor_cargo_descuento": "0.00",
            },
            "impuestos_detalle": {
                "codigo_impuesto": "0",
                "porcentaje_impuesto": "0.00",
                "valor_base_impuesto": "0.00",
                "valor_impuesto": "0.00",
            },
            "retenciones_detalle": [
                {"codigo": "0", "porcentaje": "0.00", "valor_base": "0.00", "valor_retenido": "0.00"}
            ],
            "valores_unitarios": {
                "valor_impuesto_1": "0.00",
                "valor_impuesto_2": "0.00",
                "valor_impuesto_3": "0.00",
                "valor_impuesto_4": "0.00",
                "valor_a_pagar": valor,
            },
            "valor_total_detalle_con_cargo_descuento": valor,
            "valor_total_detalle": valor,
            "informacion_adicional": [
                {"variable": "IDENTIFICACION_USUARIO", "valor": paciente}
            ],
        })

    ahora = datetime.now()
    totales = {
        "valor_base": _fmt2(total),
        "valor_base_calculo_impuestos": "0.00",
        "valor_base_mas_impuestos": _fmt2(total),
        "valor_anticipo": "0.00",
        "valor_descuento_total": "0.00",
        "valor_total_recargos": "0.00",
        "valor_total_impuesto_1": "0.00",
        "valor_total_impuesto_2": "0.00",
        "valor_total_impuesto_3": "0.00",
        "valor_total_impuesto_4": "0.00",
        "valor_total_reteiva": "0.00",
        "valor_total_retefuente": "0.00",
        "valor_total_reteica": "0.00",
        "total_nota_credito": _fmt2(total),
        "valor_total_a_pagar": _fmt2(total),
    }

    payload = {
        "documento_obligado": doc_obligado,
        "data": {
            "nota_credito": [
                {
                    "encabezado": {
                        "id_nota_credito": id_nc,
                        "fecha": ahora.strftime("%Y-%m-%d"),
                        "hora": ahora.strftime("%H:%M:%S"),
                        "nota": [
                            "{'MOTIVO':'Nota crédito parcial','SOPORTE':'Ajuste/Glosa','OBS':'Ref %s'}" % ref_doc
                        ],
                        "moneda": moneda,
                        "tipo_operacion": tipo_operacion,
                        "tipo_nota_credito": tipo_nc,
                        "numero_orden": "",
                        "prefijo": prefijo,
                    },
                    "servicio": {
                        "modo_transporte": "TERRESTRE",
                        "lugar_origen": "Bogotá",
                        "lugar_destino": "Bogotá",
                        "hora_salida": "08:30",
                        "datos_vehiculo": {"codigo": "BUS-01", "placa": "ABC123", "tipo": "AUTOBUS"},
                    },
                    "informacion_documento": {
                        "id_documento": ref_doc,
                        "codigo_unico_documento": cude_ref,
                        "fecha": ahora.strftime("%Y-%m-%d"),
                        "hora": ahora.strftime("%H:%M:%S"),
                        "codigo_tipo_documento": "TTP",
                    },
                    "detalle_factura": detalle,
                    "impuestos": [{
                        "codigo_impuesto": "0",
                        "porcentaje_impuesto": "0.00",
                        "valor_base_calculo_impuesto": "0.00",
                        "valor_total_impuesto": "0.00",
                    }],
                    "retenciones": [{
                        "codigo": "0",
                        "porcentaje": "0.00",
                        "valor_base": "0.00",
                        "valor_retenido": "0.00",
                    }],
                    "descuentos": [{
                        "codigo_descuento": "99",
                        "porcentaje_descuento": "0.00",
                        "valor_base_calculo_descuento": "0.00",
                        "valor_total_descuento": "0.00",
                    }],
                    "valor_nota_credito": totales,
                    "formas_de_pago": [{
                        "metodo_de_pago": "1",
                        "tipo_de_pago": "10",
                        "identificador_de_pago": "",
                        "fecha_vencimiento": "",
                    }],
                    "informacion_adquiriente": {
                        "tipo_contribuyente": "1",
                        "tipo_regimen": "2",
                        "tipo_identificacion": "31",
                        "identificacion": "830053105",
                        "correo_electronico": "tesoreria@cliente.com",
                        "numero_movil": "",
                        "nombre": {
                            "razon_social": "CLIENTE DEMO",
                            "primer_nombre": "",
                            "segundo_nombre": "",
                            "apellido": "",
                        },
                        "pais": "CO",
                        "departamento": "11",
                        "ciudad": "11001",
                        "direccion": "Calle 123 # 45-67",
                        "RUT": {"resp_calidades_atributos": ["O-11", "R-99-PN"], "usuario_aduanero": []},
                        "detalles_tributarios": "ZZ",
                    },
                }
            ],
            "generalidades": {
                "tipo_ambiente_dian": "2",
                "version": "1",
                "identificador_transmision": f"PKG-{id_nc}",
                "rg_tipo": "PDF",
                "rg_base_64": "",
                "integrador": {"nombre": "ERP-XXXX", "tipo": "ERP", "webhook": ""},
            },
        },
    }
    return payload


# ---------------------- Construcción AttachedDocument DIAN (desde plantilla) ----------------------

NS_AD = {
    "ad": "urn:oasis:names:specification:ubl:schema:xsd:AttachedDocument-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "ext": "urn:oasis:names:specification:ubl:schema:xsd:CommonExtensionComponents-2",
}
NS_CN = {
    "cn": "urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}


def _ensure_text(el, text):
    if el is not None:
        el.text = text


def _set_money(el, amount: Decimal, currency: str = "COP"):
    if el is None:
        return
    el.set("currencyID", currency)
    el.text = _fmt2(amount)


def construir_attacheddocument_desde_plantilla(
    template_bytes: bytes,
    *,
    id_nc: str,
    parent_document_id: str,
    filas_df: pd.DataFrame,
    modo_lineas: str = "UNA_LINEA",  # "UNA_LINEA" | "POR_SERVICIO"
    moneda: str = "COP",
) -> bytes:
    """
    Reutiliza el AttachedDocument DE PLANTILLA (válido).
    - Verifica que exista cbc:Description y que contenga un CreditNote (UBL) en CDATA.
    - Reemplaza: cbc:ID, cbc:ParentDocumentID, cbc:LineCountNumeric y las líneas CreditNoteLine.
    - Recalcula totales (PayableAmount, TaxExclusiveAmount, LineExtensionAmount).
    - NO cambia otros nodos (firma, profile, extensiones, etc.). OJO: la firma queda inválida si existía.
    """
    parser = etree.XMLParser(remove_blank_text=False)
    ad_root = etree.fromstring(template_bytes, parser=parser)

    # Comprobar que es AttachedDocument
    if ad_root.tag.endswith("AttachedDocument") is False:
        raise ValueError("El XML cargado no es un AttachedDocument válido.")

    # ID y ParentDocumentID del contenedor
    id_node = ad_root.find(".//cbc:ID", namespaces=NS_AD)
    parent_node = ad_root.find(".//cbc:ParentDocumentID", namespaces=NS_AD)
    _ensure_text(id_node, id_nc)
    _ensure_text(parent_node, parent_document_id)

    # cbc:Description con CDATA que contiene el CreditNote
    desc = ad_root.find(".//cbc:Description", namespaces=NS_AD)
    if desc is None or desc.text is None or "<CreditNote" not in desc.text:
        raise ValueError("No se encontró cbc:Description con CreditNote en CDATA dentro de la plantilla.")

    # Parsear el CreditNote interno
    cn_root = etree.fromstring(desc.text.encode("utf-8"), parser=etree.XMLParser(remove_blank_text=False))

    # ID de la NC y line count
    cn_id = cn_root.find("./cbc:ID", namespaces=NS_CN)
    _ensure_text(cn_id, id_nc)
    cn_linecount = cn_root.find("./cbc:LineCountNumeric", namespaces=NS_CN)

    # Calcular líneas y totales
    sel = filas_df[filas_df["incluir"] == True].copy()  # noqa: E712
    if sel.empty:
        raise ValueError("No hay ítems seleccionados para reflejar en el CreditNote.")

    if modo_lineas == "UNA_LINEA":
        total = Decimal("0.00")
        for row in sel.itertuples(index=False):
            total += _dec(row.valor_nc)

        # Borrar todas las CreditNoteLine existentes
        for old in cn_root.findall(".//cac:CreditNoteLine", namespaces=NS_CN):
            old.getparent().remove(old)

        # Crear una sola línea (ID=1)
        line = etree.SubElement(cn_root, f"{{{NS_CN['cac']}}}CreditNoteLine")
        etree.SubElement(line, f"{{{NS_CN['cbc']}}}ID").text = "1"
        qty = etree.SubElement(line, f"{{{NS_CN['cbc']}}}CreditedQuantity")
        qty.set("unitCode", "94")
        qty.text = "1"
        lea = etree.SubElement(line, f"{{{NS_CN['cbc']}}}LineExtensionAmount")
        _set_money(lea, total, moneda)

        # LineCountNumeric = 1
        _ensure_text(cn_linecount, "1")

        total_payable = total

    else:  # "POR_SERVICIO"
        # Borrar todas las CreditNoteLine existentes
        for old in cn_root.findall(".//cac:CreditNoteLine", namespaces=NS_CN):
            old.getparent().remove(old)

        total_payable = Decimal("0.00")
        for i, row in enumerate(sel.itertuples(index=False), start=1):
            v = _dec(row.valor_nc)
            total_payable += v
            line = etree.SubElement(cn_root, f"{{{NS_CN['cac']}}}CreditNoteLine")
            etree.SubElement(line, f"{{{NS_CN['cbc']}}}ID").text = str(i)
            qty = etree.SubElement(line, f"{{{NS_CN['cbc']}}}CreditedQuantity")
            qty.set("unitCode", "94")
            qty.text = "1"
            lea = etree.SubElement(line, f"{{{NS_CN['cbc']}}}LineExtensionAmount")
            _set_money(lea, v, moneda)

        _ensure_text(cn_linecount, str(len(sel)))

    # Ajustar totales monetarios comunes si existen
    # LegalMonetaryTotal/PayableAmount
    pay_amount = cn_root.find(".//cac:LegalMonetaryTotal/cbc:PayableAmount", namespaces=NS_CN)
    _set_money(pay_amount, total_payable, moneda)

    # TaxExclusiveAmount (si existe en la plantilla)
    tax_excl = cn_root.find(".//cbc:TaxExclusiveAmount", namespaces=NS_CN)
    if tax_excl is not None:
        _set_money(tax_excl, total_payable, moneda)

    # LineExtensionAmount a nivel global (si existe)
    glob_lea = cn_root.find("./cbc:LineExtensionAmount", namespaces=NS_CN)
    if glob_lea is not None:
        _set_money(glob_lea, total_payable, moneda)

    # Reinyectar el CreditNote como CDATA
    cn_bytes = etree.tostring(cn_root, encoding="utf-8", xml_declaration=True, standalone="no")
    desc.text = etree.CDATA(cn_bytes.decode("utf-8"))

    # Serializar todo el AttachedDocument
    return etree.tostring(ad_root, xml_declaration=True, encoding="utf-8")


# ---------------------- UI Streamlit ----------------------

st.set_page_config(page_title="NC (JSON TTP + AttachedDocument DIAN)", page_icon="🧾", layout="wide")
st.title("🧾 Generador de Nota Crédito — JSON TTP + AttachedDocument DIAN (desde plantilla)")

with st.expander("1) Cargar archivos de entrada", expanded=True):
    c1, c2 = st.columns(2)
    with c1:
        up_rips = st.file_uploader("RipsDocumento JSON (nota crédito)", type=["json"], accept_multiple_files=False)
        st.caption("Debe contener `usuarios[].servicios.*[].vrServicio` para detectar valores de nota.")
    with c2:
        up_tpl = st.file_uploader("AttachedDocument DIAN (PLANTILLA válida)", type=["xml"], accept_multiple_files=False)
        st.caption("Usa aquí **tu XML que ya pasó validador**. No se alterará la estructura, solo valores mínimos.")

    loaded_rips = None
    tpl_bytes = None
    if up_rips is not None:
        try:
            loaded_rips = _load_json_bytes(up_rips.read())
            st.success("RipsDocumento cargado.")
        except Exception as e:
            st.error(f"JSON inválido: {e}")

    if up_tpl is not None:
        try:
            tpl_bytes = up_tpl.read()
            # Validación rápida de que sea AttachedDocument y contenga Description con CreditNote
            _ = construir_attacheddocument_desde_plantilla(
                tpl_bytes, id_nc="__TEST__", parent_document_id="__TEST__", filas_df=pd.DataFrame([{"incluir": True, "valor_nc": 1}]), modo_lineas="UNA_LINEA"
            )
            st.success("Plantilla AttachedDocument válida (se detectó CreditNote en CDATA).")
        except Exception as e:
            st.error(f"Plantilla inválida: {e}")
            tpl_bytes = None

with st.expander("2) Seleccionar y editar valores de la Nota", expanded=True):
    df = pd.DataFrame()
    if loaded_rips is not None:
        filas = extraer_servicios_con_valor(loaded_rips)
        if not filas:
            st.warning("No se encontraron servicios con `vrServicio > 0` en el JSON.")
        else:
            df = pd.DataFrame(filas)
            st.caption("Marca los ítems a incluir y ajusta `valor_nc` según corresponda.")
            edited = st.data_editor(
                df,
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "incluir": st.column_config.CheckboxColumn("Incluir", help="Marcar para aplicar NC"),
                    "valor_original": st.column_config.NumberColumn("Valor original", format="%.2f", disabled=True),
                    "valor_nc": st.column_config.NumberColumn("Valor NC", format="%.2f"),
                },
                hide_index=True,
            )
            df = edited

            colA, colB = st.columns(2)
            with colA:
                if st.button("⬇️ Descargar plantilla Excel (edición masiva)"):
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="xlsxwriter") as wr:
                        df.to_excel(wr, index=False, sheet_name="NC")
                    st.download_button(
                        "Descargar NC.xlsx",
                        buf.getvalue(),
                        file_name="plantilla_nc.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
            with colB:
                up_xlsx = st.file_uploader("Cargar plantilla Excel editada", type=["xlsx"])
                if up_xlsx is not None:
                    try:
                        dfx = pd.read_excel(up_xlsx)
                        # Merge por claves (u_idx, s_idx, tabla, paciente)
                        keys = ["u_idx", "s_idx", "tabla", "paciente"]
                        df = df.drop(columns=["valor_nc"], errors="ignore").merge(
                            dfx[keys + ["valor_nc", "incluir"]],
                            on=keys, how="left", suffixes=("", "_x")
                        )
                        # Si vienen NaN en valor_nc (no editados), repone el existente
                        df["valor_nc"] = df["valor_nc"].fillna(df["valor_original"])
                        df["incluir"] = df["incluir"].fillna(True)
                        st.success("Plantilla aplicada.")
                    except Exception as e:
                        st.error(f"No se pudo leer el Excel: {e}")
            if not df.empty:
                total_sel = df[df["incluir"] == True]["valor_nc"].sum()  # noqa: E712
                st.info(f"Total seleccionado: **{_fmt2(total_sel)}**")

with st.expander("3) Parámetros de la Nota y salida", expanded=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        id_nc = st.text_input("ID Nota Crédito", "NC23349")
        ref_doc = st.text_input("Documento Referenciado (ParentDocumentID)", "SM13660")
        cude = st.text_input("CUDE/Código Único del doc referenciado", "CUDE_DE_LA_FACTURA_O_DOC")
    with c2:
        doc_obligado = st.text_input("NIT del obligado (documento_obligado)", "901002487")
        prefijo = st.text_input("Prefijo", "NC")
        moneda = st.text_input("Moneda", "COP")
    with c3:
        modo_lineas = st.selectbox("Líneas en CreditNote", ["UNA_LINEA", "POR_SERVICIO"], index=0)
        construir_json = st.button("🧩 Construir JSON Afacturar/TTP", use_container_width=True)
        construir_xml  = st.button("📎 Construir AttachedDocument XML", use_container_width=True)

    if "payload" not in st.session_state:
        st.session_state["payload"] = None
    if "xml_bytes" not in st.session_state:
        st.session_state["xml_bytes"] = None

    if construir_json:
        try:
            if df.empty:
                st.warning("Primero carga el JSON RipsDocumento y selecciona/edita valores.")
            else:
                payload = construir_payload_afacturar_ttp(
                    loaded_rips, df,
                    id_nc=id_nc, ref_doc=ref_doc, cude_ref=cude,
                    doc_obligado=doc_obligado, moneda=moneda, prefijo=prefijo
                )
                st.session_state["payload"] = payload
                st.success("JSON construido.")
                st.code(json.dumps(payload, ensure_ascii=False, indent=2), language="json")
        except Exception as e:
            st.error(f"Error construyendo JSON: {e}")

    if construir_xml:
        try:
            if tpl_bytes is None:
                st.warning("Debes cargar primero el AttachedDocument de PLANTILLA (válido).")
            elif df.empty:
                st.warning("Primero carga el JSON RipsDocumento y selecciona/edita valores.")
            else:
                xml_out = construir_attacheddocument_desde_plantilla(
                    tpl_bytes, id_nc=id_nc, parent_document_id=ref_doc,
                    filas_df=df, modo_lineas=modo_lineas, moneda=moneda
                )
                st.session_state["xml_bytes"] = xml_out
                st.success("AttachedDocument construido (estructura preservada).")
        except Exception as e:
            st.error(f"Error construyendo AttachedDocument: {e}")

    colx, coly = st.columns(2)
    with colx:
        if st.session_state.get("payload"):
            st.download_button(
                "⬇️ Descargar JSON Afacturar",
                data=json.dumps(st.session_state["payload"], ensure_ascii=False, indent=2).encode("utf-8"),
                file_name=f"{id_nc}_payload.json",
                mime="application/json",
                use_container_width=True
            )
    with coly:
        if st.session_state.get("xml_bytes"):
            st.download_button(
                "⬇️ Descargar AttachedDocument XML",
                data=st.session_state["xml_bytes"],
                file_name=f"{id_nc}_AttachedDocument.xml",
                mime="application/xml",
                use_container_width=True
            )

st.caption("⚠️ Si la PLANTILLA tenía firma XAdES, debes firmar nuevamente el XML final para validadores que exijan firma.")
