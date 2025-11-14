# app_rips_notas2.py
import json, traceback
import streamlit as st
import requests
from datetime import datetime

# importa SOLO desde el módulo (no al revés)
from afacturar_nota_credito import construir_payload_nota_credito, _fmt_dec

st.set_page_config(page_title="NC Afacturar (TTP)", page_icon="🧾", layout="wide")
st.write("✅ App cargando… (checkpoint UI)")

def _safe_main(run):
    try:
        run()
    except Exception:
        st.error("💥 La app falló durante la ejecución.")
        st.code(traceback.format_exc())

def main():
    st.title("🧾 Generador y Envío de Nota Crédito (Afacturar TTP)")

    with st.sidebar:
        st.subheader("Conexión")
        ambiente = st.selectbox("Ambiente DIAN/Afacturar", ["PRUEBAS","HABILITACIÓN","PRODUCCIÓN"], index=0)
        base = {
            "PRUEBAS": "https://servicios-pruebas.afacturar.com",
            "HABILITACIÓN": "https://servicios-habilitacion.afacturar.com",
            "PRODUCCIÓN": "https://servicios.afacturar.com"
        }[ambiente]
        token_sugerido = ""
        try:
            token_sugerido = st.secrets.get("AFACTURAR_TOKEN","")
        except Exception:
            token_sugerido = ""
        usar_secret = st.checkbox("Usar st.secrets['AFACTURAR_TOKEN']", value=bool(token_sugerido))
        token = st.text_input("Bearer Token", value=(token_sugerido if usar_secret else ""), type="password",
                              help="Pega el token que te dio Afacturar. No incluyas 'Bearer'.")

    st.markdown("### 1) Encabezado")
    col1, col2, col3, col4 = st.columns(4)
    with col1: id_nc = st.text_input("id_nota_credito", "NC23349")
    with col2: fecha = st.text_input("fecha (AAAA-MM-DD)", datetime.now().strftime("%Y-%m-%d"))
    with col3: hora = st.text_input("hora (HH:MM:SS)", datetime.now().strftime("%H:%M:%S"))
    with col4: prefijo = st.text_input("prefijo", "NC")
    colA, colB, colC = st.columns(3)
    with colA: moneda = st.text_input("moneda", "COP")
    with colB: tipo_operacion = st.text_input("tipo_operacion", "35")
    with colC: tipo_nc = st.text_input("tipo_nota_credito (1..5)", "4")
    nota_libre = st.text_area("nota (string con comillas simples)", "{'MOTIVO':'Ajuste','OBS':'Prueba integración'}", height=80)

    st.markdown("### 2) Documento afectado")
    doc_id = st.text_input("id_documento", "TT-000123")
    cude = st.text_input("codigo_unico_documento (CUDE)", "CUDE_DE_LA_FACTURA_O_DOC")
    colF1, colF2 = st.columns(2)
    with colF1: doc_fecha = st.text_input("fecha doc (AAAA-MM-DD)", fecha)
    with colF2: doc_hora = st.text_input("hora doc (HH:MM:SS)", "08:15:00")
    cod_tipo_doc = st.text_input("codigo_tipo_documento", "TTP")

    st.markdown("### 3) Servicio y detalle")
    colS1, colS2, colS3 = st.columns(3)
    with colS1: origen = st.text_input("lugar_origen", "Bogotá")
    with colS2: destino = st.text_input("lugar_destino", "Medellín")
    with colS3: hora_salida = st.text_input("hora_salida (HH:MM)", "08:30")
    placa = st.text_input("placa", "ABC123")

    st.markdown("##### Línea de detalle")
    colD1, colD2, colD3 = st.columns(3)
    with colD1: cantidad = st.number_input("cantidad", min_value=1.0, value=1.0, step=1.0)
    with colD2: unidad = st.text_input("unidad_de_cantidad", "94")
    with colD3: vu = st.text_input("valor_unitario", _fmt_dec("4992000"))
    desc = st.text_input("descripcion", "Servicio transporte pasajero")
    nota_detalle = st.text_input("nota_detalle", "Ajuste parcial")

    st.markdown("### 4) Totales")
    total = st.text_input("total_nota_credito", _fmt_dec("4992000"))
    total_pagar = st.text_input("valor_total_a_pagar", _fmt_dec("4992000"))

    st.markdown("### 5) Emisor / generalidades")
    doc_obligado = st.text_input("documento_obligado (NIT emisor)", "901002487")
    tipo_amb = "2" if ambiente != "PRODUCCIÓN" else "1"

    colBtn1, colBtn2, colBtn3 = st.columns(3)

    if colBtn1.button("🧩 Construir JSON"):
        try:
            encabezado = {
                "id_nota_credito": id_nc, "fecha": fecha, "hora": hora,
                "moneda": moneda, "tipo_operacion": tipo_operacion,
                "tipo_nota_credito": tipo_nc, "prefijo": prefijo,
                "nota": [nota_libre] if nota_libre.strip() else []
            }
            servicio = {
                "modo_transporte": "TERRESTRE",
                "lugar_origen": origen, "lugar_destino": destino,
                "hora_salida": hora_salida,
                "datos_vehiculo": {"codigo": placa, "placa": placa, "tipo": "AUTOBUS"}
            }
            info_doc = {
                "id_documento": doc_id, "codigo_unico_documento": cude,
                "fecha": doc_fecha, "hora": doc_hora, "codigo_tipo_documento": cod_tipo_doc
            }
            detalle = [{
                "numero_linea": 1, "cantidad": cantidad, "unidad_de_cantidad": unidad,
                "valor_unitario": _fmt_dec(vu),
                "descripcion": desc, "nota_detalle": nota_detalle,
                "marca": "N/A", "modelo": "N/A",
                "codificacion_estandar": {
                    "cod_grupo_bien_servicio": "1", "nombre_grupo_bien_servicio": "UNSPSC",
                    "cod_segmento_bien_servicio": "7811", "cod_bien_servicio": "78111000"
                },
                "regalo": {"es_regalo": False, "cod_precio_referencia": "0", "precio_referencia": _fmt_dec("0")},
                "cargo_descuento": {"es_descuento": True, "porcentaje_cargo_descuento": _fmt_dec("0.00"),
                                    "valor_base_cargo_descuento": _fmt_dec("0"), "valor_cargo_descuento": _fmt_dec("0")},
                "impuestos_detalle": {"codigo_impuesto":"0","porcentaje_impuesto":_fmt_dec("0.00"),
                                      "valor_base_impuesto":_fmt_dec("0"),"valor_impuesto":_fmt_dec("0")},
                "retenciones_detalle":[{"codigo":"0","porcentaje":_fmt_dec("0.00"),
                                        "valor_base":_fmt_dec("0"),"valor_retenido":_fmt_dec("0")}],
                "valores_unitarios":{"valor_impuesto_1":_fmt_dec("0"),"valor_impuesto_2":_fmt_dec("0"),
                                     "valor_impuesto_3":_fmt_dec("0"),"valor_impuesto_4":_fmt_dec("0"),
                                     "valor_a_pagar":_fmt_dec(total)},
                "valor_total_detalle_con_cargo_descuento": _fmt_dec(total),
                "valor_total_detalle": _fmt_dec(total),
                "informacion_adicional":[{"variable":"DESCRIPCION","valor":"Servicio parcial"}],
                "datos_remesa":{"tipo_servicio":"0","numero_radicado_de_la_remesa":"N/A",
                                "numero_de_remesa":"N/A","valor_flete":"0","cantidad_transportada":"0","unidad_medida":"KGM"}
            }]
            impuestos = [{"codigo_impuesto":"0","porcentaje_impuesto":_fmt_dec("0.00"),
                          "valor_base_calculo_impuesto":_fmt_dec("0"),"valor_total_impuesto":_fmt_dec("0")}]
            descuentos = [{"codigo_descuento":"99","porcentaje_descuento":_fmt_dec("0.00"),
                           "valor_base_calculo_descuento":_fmt_dec("0"),"valor_total_descuento":_fmt_dec("0")}]
            valor_nc = {
                "valor_base": _fmt_dec(total), "valor_base_calculo_impuestos": _fmt_dec("0"),
                "valor_base_mas_impuestos": _fmt_dec(total), "valor_anticipo": _fmt_dec("0"),
                "valor_descuento_total": _fmt_dec("0"), "valor_total_recargos": _fmt_dec("0"),
                "valor_total_impuesto_1": _fmt_dec("0"), "valor_total_impuesto_2": _fmt_dec("0"),
                "valor_total_impuesto_3": _fmt_dec("0"), "valor_total_impuesto_4": _fmt_dec("0"),
                "valor_total_reteiva": _fmt_dec("0"), "valor_total_retefuente": _fmt_dec("0"),
                "valor_total_reteica": _fmt_dec("0"), "total_nota_credito": _fmt_dec(total),
                "valor_total_a_pagar": _fmt_dec(total_pagar)
            }
            generalidades = {
                "tipo_ambiente_dian": ("2" if ambiente != "PRODUCCIÓN" else "1"),
                "version": "1", "identificador_transmision": f"PKG-{id_nc}",
                "rg_tipo": "PDF", "rg_base_64": "",
                "integrador": {"nombre":"ERP-LOCAL","tipo":"ERP","webhook":""}
            }

            payload = construir_payload_nota_credito(
                documento_obligado=doc_obligado,
                encabezado=encabezado,
                servicio=servicio,
                informacion_documento=info_doc,
                detalle_factura=detalle,
                impuestos=impuestos,
                descuentos=descuentos,
                valor_nota_credito=valor_nc,
                generalidades=generalidades
            )
            st.success("✅ Payload construido.")
            st.code(json.dumps(payload, ensure_ascii=False, indent=2), language="json")
            st.session_state["payload"] = payload
            st.session_state["base"] = base
            st.session_state["token"] = token
        except Exception:
            st.error("Error construyendo el payload.")
            st.code(traceback.format_exc())

    if colBtn2.button("⬇️ Descargar JSON"):
        if "payload" not in st.session_state:
            st.warning("Primero construye el JSON.")
        else:
            data = json.dumps(st.session_state["payload"], ensure_ascii=False, indent=2).encode("utf-8")
            st.download_button("Descargar archivo", data=data,
                               file_name=f"{id_nc}_nota_credito.json", mime="application/json", use_container_width=True)

    if colBtn3.button("🚀 Enviar a Afacturar"):
        try:
            if "payload" not in st.session_state:
                st.warning("Primero construye el JSON.")
                return
            base = st.session_state.get("base", "")
            token_val = st.session_state.get("token", "").strip()
            if not token_val:
                st.error("Falta Bearer Token. Cópialo en la barra lateral.")
                return
            url = f"{base}/api/doc_equivalente/TTP/nota_credito"
            headers = {
                "Accept":"application/json",
                "Authorization": f"Bearer {token_val}",
                "Content-Type":"application/json"
            }
            with st.spinner("Enviando…"):
                r = requests.post(url, headers=headers, json=st.session_state["payload"], timeout=90)
            st.write("Status:", r.status_code)
            try:
                st.json(r.json())
            except Exception:
                st.code(r.text)
        except Exception:
            st.error("Error en el envío.")
            st.code(traceback.format_exc())

_safe_main(main)
