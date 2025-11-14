# afacturar_nota_credito.py
# Generador de JSON para Afacturar - Doc Equivalente TTP / Nota Crédito
# - Construye la estructura completa según la especificación que compartiste.
# - Formatea decimales ("#.##"), normaliza strings y arma la 'nota' como string pseudo-JSON con comillas simples.
# - Divide 'nota' en trozos (lista) cumpliendo longitud mínima (>=15) y límite configurable.
# - Incluye un ejemplo de POST al endpoint de Pruebas.

from __future__ import annotations
import json
import re
from typing import Dict, Any, List, Optional
import requests
from datetime import datetime

# =============== Helpers de formato ===============

def _fmt_dec(val: float | int | str, dec: int = 2) -> str:
    """
    Formatea a string con punto y 'dec' decimales. Acepta '1,23' y lo normaliza.
    """
    if isinstance(val, str):
        val = val.replace(",", ".").strip()
        try:
            val = float(val)
        except Exception:
            raise ValueError(f"Valor numérico inválido: {val}")
    return f"{float(val):.{dec}f}"

def _sanitize_text(s: str, min_len: int = 0) -> str:
    """
    Limpia saltos de línea, tabulaciones y espacios repetidos.
    (La API no acepta backslash secuencias raras dentro de 'nota').
    """
    if s is None:
        s = ""
    s = re.sub(r"[\r\n\t]+", " ", str(s))
    s = re.sub(r"\s{2,}", " ", s).strip()
    if len(s) < min_len:
        s = s + (" " * (min_len - len(s)))
    return s

def _nota_to_single_quote_string(nota_dict: Dict[str, Any]) -> str:
    """
    Convierte un dict a el string tipo JSON con comillas simples que exige Afacturar:
      {'k1':'v1','k2':'v2'}
    - Sustituye comillas simples internas en valores por un espacio (o podrías escaparlas si Afacturar lo soporta).
    - Quita backslashes no deseados.
    """
    pairs = []
    for k, v in nota_dict.items():
        key = str(k)
        if isinstance(v, (dict, list)):
            # Si quieres anidar, conviértelo a un JSON compacto y reemplaza comillas dobles por simples.
            v_str = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        else:
            v_str = str(v)

        # Limpiezas para cumplir restricciones del campo 'nota'
        v_str = v_str.replace("\\'", " ")  # backslash comilla
        v_str = v_str.replace("\\", " ")   # backslash suelto
        v_str = v_str.replace("'", " ")    # comilla simple interna -> espacio
        v_str = _sanitize_text(v_str)

        key = key.replace("'", " ")  # por si acaso
        pair = f"'{key}':'{v_str}'"
        pairs.append(pair)
    return "{" + ",".join(pairs) + "}"

def _split_nota_string(nota_str: str, max_len: int = 1000, min_piece: int = 15) -> List[str]:
    """
    Divide el string de 'nota' en un array de fragmentos (cumple mínimo 15 chars).
    - max_len: tamaño máximo por pieza (ajústalo si tu proveedor recomienda otro).
    - min_piece: si el último queda <15, lo pega al anterior para cumplir.
    """
    nota_str = _sanitize_text(nota_str)
    chunks = [nota_str[i:i+max_len] for i in range(0, len(nota_str), max_len)] or [nota_str]
    if len(chunks[-1]) < min_piece and len(chunks) > 1:
        chunks[-2] = chunks[-2] + chunks[-1]
        chunks = chunks[:-1]
    # Si por alguna razón queda <15 en único fragmento, lo rellenamos con espacios.
    if len(chunks) == 1 and len(chunks[0]) < min_piece:
        chunks[0] = chunks[0] + (" " * (min_piece - len(chunks[0])))
    return chunks

# =============== Constructor principal ===============

def construir_payload_nota_credito(
    documento_obligado: str,
    encabezado: Dict[str, Any],
    servicio: Dict[str, Any],
    informacion_documento: Dict[str, Any],
    detalle_factura: List[Dict[str, Any]],
    impuestos: List[Dict[str, Any]],
    descuentos: List[Dict[str, Any]],
    valor_nota_credito: Dict[str, Any],
    generalidades: Dict[str, Any],
    formas_de_pago: Optional[List[Dict[str, Any]]] = None,
    cambio_de_moneda: Optional[Dict[str, Any]] = None,
    retenciones: Optional[List[Dict[str, Any]]] = None,
    recargos: Optional[List[Dict[str, Any]]] = None,
    cambio_de_moneda_totales: Optional[Dict[str, Any]] = None,
    entrega_de_bienes: Optional[Dict[str, Any]] = None,
    informacion_adquiriente: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Devuelve el cuerpo JSON que pide Afacturar:
    {
      "documento_obligado": "...",
      "data": { "nota_credito": [...], "generalidades": {...} }
    }
    """
    # --- Validaciones mínimas (puedes expandir) ---
    for req in ["id_nota_credito", "fecha", "hora", "moneda", "tipo_operacion", "tipo_nota_credito"]:
        if req not in encabezado:
            raise ValueError(f"encabezado.{req} es requerido.")
    if not isinstance(detalle_factura, list) or len(detalle_factura) == 0:
        raise ValueError("detalle_factura debe ser lista con al menos un ítem.")
    if not isinstance(impuestos, list) or len(impuestos) == 0:
        raise ValueError("impuestos debe ser lista con al menos un ítem.")
    if not isinstance(descuentos, list) or len(descuentos) == 0:
        raise ValueError("descuentos debe ser lista con al menos un ítem.")
    if "id_documento" not in informacion_documento or "fecha" not in informacion_documento or "hora" not in informacion_documento or ("codigo_unico_factura" not in informacion_documento and "codigo_unico_documento" not in informacion_documento):
        raise ValueError("informacion_documento requiere id_documento, fecha, hora y CUDE (codigo_unico_factura o codigo_unico_documento).")

    # --- Armar 'nota' como string con comillas simples y luego dividirlo en un array ---
    # Sugerencia: incluye conceptos claves que Afacturar y DIAN esperan como descripción/observaciones.
    nota_dict = {
        "MOTIVO": "Nota crédito parcial por ajuste de precio",
        "SOPORTE": "Glosa parcial sobre servicios",
        "OBS": f"NC {encabezado.get('id_nota_credito','')}, Ref doc {informacion_documento.get('id_documento','')}",
    }
    # Si ya te pasan nota desde 'encabezado', respétalo y sólo normalízalo:
    if "nota" in encabezado and encabezado["nota"]:
        # Si te llega como lista de strings, la concatenas y normalizas
        if isinstance(encabezado["nota"], list):
            base = "".join(str(x) for x in encabezado["nota"])
            base = _sanitize_text(base)
            # No intentes parsear; sólo garantizamos condiciones mínimas
            nota_str = base
        else:
            # Si te llega un string (ya tipo {'k':'v'} ), lo usamos
            nota_str = _sanitize_text(str(encabezado["nota"]))
    else:
        # Construimos automáticamente
        nota_str = _nota_to_single_quote_string(nota_dict)

    nota_partes = _split_nota_string(nota_str, max_len=1000, min_piece=15)

    # --- Normalizar / asegurar mínimos en dinero de totales (2 decimales como string) ---
    def norm_totales(d: Dict[str, Any], keys_dec: List[str]) -> Dict[str, Any]:
        nd = dict(d)
        for k in keys_dec:
            if k in nd and nd[k] not in (None, ""):
                nd[k] = _fmt_dec(nd[k], 2)
        return nd

    valor_nota_credito = norm_totales(
        valor_nota_credito,
        [
            "valor_base", "valor_base_calculo_impuestos", "valor_base_mas_impuestos",
            "valor_anticipo", "valor_descuento_total", "valor_total_recargos",
            "valor_total_impuesto_1","valor_total_impuesto_2","valor_total_impuesto_3","valor_total_impuesto_4",
            "valor_total_reteiva","valor_total_retefuente","valor_total_reteica",
            "total_nota_credito","valor_total_a_pagar"
        ]
    )
    if cambio_de_moneda_totales:
        cambio_de_moneda_totales = norm_totales(
            cambio_de_moneda_totales,
            [
                "valor_base","valor_base_calculo_impuestos","valor_base_mas_impuestos",
                "valor_anticipo","valor_descuento_total","valor_total_recargos",
                "valor_total_impuesto_1","valor_total_impuesto_2","valor_total_impuesto_3","valor_total_impuesto_4",
                "valor_total_reteiva","valor_total_retefuente","valor_total_reteica",
                "total_nota_credito","valor_total_a_pagar"
            ]
        )

    # --- Ensamble final ---
    data_nc: Dict[str, Any] = {
        "encabezado": {
            "id_nota_credito": _sanitize_text(encabezado["id_nota_credito"]),
            "fecha": _sanitize_text(encabezado["fecha"]),
            "hora": _sanitize_text(encabezado["hora"]),
            "nota": nota_partes,
            "moneda": encabezado["moneda"],                # "COP" / "USD"
            "tipo_operacion": encabezado["tipo_operacion"],# "35"
            "tipo_nota_credito": encabezado["tipo_nota_credito"],  # 1..5
            "numero_orden": _sanitize_text(encabezado.get("numero_orden","")),
            "prefijo": _sanitize_text(encabezado.get("prefijo","")),
        },
        "servicio": servicio,
        "informacion_documento": {
            "id_documento": _sanitize_text(informacion_documento.get("id_documento","")),
            "codigo_unico_documento": _sanitize_text(informacion_documento.get("codigo_unico_documento", informacion_documento.get("codigo_unico_factura",""))),
            "fecha": _sanitize_text(informacion_documento.get("fecha","")),
            "hora": _sanitize_text(informacion_documento.get("hora","")),
            "codigo_tipo_documento": _sanitize_text(informacion_documento.get("codigo_tipo_documento","")),
        },
        "detalle_factura": detalle_factura,
        "impuestos": impuestos,
        "descuentos": descuentos,
        "valor_nota_credito": valor_nota_credito,
    }

    if formas_de_pago:
        data_nc["formas_de_pago"] = formas_de_pago
    if cambio_de_moneda:
        data_nc["cambio_de_moneda"] = cambio_de_moneda
    if retenciones:
        data_nc["retenciones"] = retenciones
    if recargos:
        data_nc["recargos"] = recargos
    if cambio_de_moneda_totales:
        data_nc["cambio_de_moneda_totales"] = cambio_de_moneda_totales
    if entrega_de_bienes:
        data_nc["entrega_de_bienes"] = entrega_de_bienes
    if informacion_adquiriente:
        data_nc["informacion_adquiriente"] = informacion_adquiriente

    payload = {
        "documento_obligado": _sanitize_text(documento_obligado),
        "data": {
            "nota_credito": [ data_nc ],
            "generalidades": generalidades
        }
    }
    return payload

# =============== Ejemplo mínimo de armado + POST ===============

def ejemplo_construccion_y_envio():
    """
    Rellena con tus datos (TODO) y prueba un envío a PRUEBAS.
    """
    # ====== TODO: completa con tus valores reales ======
    documento_obligado = "901002487"  # NIT del emisor (sin dígito de verificación normalmente)
    encabezado = {
        "id_nota_credito": "NC23349",
        "fecha": datetime.now().strftime("%Y-%m-%d"),
        "hora": datetime.now().strftime("%H:%M:%S"),
        "moneda": "COP",
        "tipo_operacion": "35",
        "tipo_nota_credito": "4",  # (1..5) p.ej. 4= Ajuste de precio
        "prefijo": "NC",
        # "nota": ["{'MOTIVO':'Ajuste','OBS':'Prueba integración'}"]  # opcional si ya la armas tú
    }
    servicio = {
        "modo_transporte": "TERRESTRE",
        "lugar_origen": "Bogotá",
        "lugar_destino": "Medellín",
        "hora_salida": "08:30",
        "datos_vehiculo": {
            "codigo": "BUS-01",
            "placa": "ABC123",
            "tipo": "AUTOBUS"
        }
    }
    informacion_documento = {
        "id_documento": "TT-000123",              # ID del doc equivalente afectado
        "codigo_unico_documento": "CUDE_DE_LA_FACTURA_O_DOC",  # CUDE/UUID del documento afectado
        "fecha": "2025-11-06",
        "hora": "08:15:00",
        "codigo_tipo_documento": "TTP"            # si te lo exigen
    }
    detalle_factura = [
        {
            "numero_linea": 1,
            "cantidad": 1,
            "unidad_de_cantidad": "94",  # Unidad
            "valor_unitario": _fmt_dec("4992000"),
            "descripcion": "Servicio transporte pasajero",
            "nota_detalle": "Ajuste parcial",
            "marca": "N/A",
            "modelo": "N/A",
            "codificacion_estandar": {
                "cod_grupo_bien_servicio": "1",      # 1=UNSPSC / 10=GTIN / 20=Partida / 999=Propio
                "nombre_grupo_bien_servicio": "UNSPSC",
                "cod_segmento_bien_servicio": "7811",
                "cod_bien_servicio": "78111000"
            },
            "regalo": {
                "es_regalo": False,
                "cod_precio_referencia": "0",        # 1=Valor comercial, 0=no regalo
                "precio_referencia": _fmt_dec("0")
            },
            "cargo_descuento": {
                "es_descuento": True,
                "porcentaje_cargo_descuento": _fmt_dec("0.00"),
                "valor_base_cargo_descuento": _fmt_dec("0"),
                "valor_cargo_descuento": _fmt_dec("0")
            },
            "impuestos_detalle": {
                "codigo_impuesto": "0",              # 0=Excluido
                "porcentaje_impuesto": _fmt_dec("0.00"),
                "valor_base_impuesto": _fmt_dec("0"),
                "valor_impuesto": _fmt_dec("0")
            },
            "retenciones_detalle": [
                {
                    "codigo": "0",
                    "porcentaje": _fmt_dec("0.00"),
                    "valor_base": _fmt_dec("0"),
                    "valor_retenido": _fmt_dec("0")
                }
            ],
            "valores_unitarios": {
                "valor_impuesto_1": _fmt_dec("0"),
                "valor_impuesto_2": _fmt_dec("0"),
                "valor_impuesto_3": _fmt_dec("0"),
                "valor_impuesto_4": _fmt_dec("0"),
                "valor_a_pagar": _fmt_dec("4992000")
            },
            "valor_total_detalle_con_cargo_descuento": _fmt_dec("4992000"),
            "valor_total_detalle": _fmt_dec("4992000"),
            "informacion_adicional": [
                {"variable": "DESCRIPCION", "valor": "Servicio parcial"},
                {"variable": "IDENTIFICACION_USUARIO", "valor": "100000055"}
            ],
            "datos_remesa": {
                "tipo_servicio": "0",
                "numero_radicado_de_la_remesa": "N/A",
                "numero_de_remesa": "N/A",
                "valor_flete": "0",
                "cantidad_transportada": "0",
                "unidad_medida": "KGM"
            }
        }
    ]
    impuestos = [
        {
            "codigo_impuesto": "0",
            "porcentaje_impuesto": _fmt_dec("0.00"),
            "valor_base_calculo_impuesto": _fmt_dec("0"),
            "valor_total_impuesto": _fmt_dec("0")
        }
    ]
    descuentos = [
        {
            "codigo_descuento": "99",  # 99= No aplica descuento (si aplica, ajusta)
            "porcentaje_descuento": _fmt_dec("0.00"),
            "valor_base_calculo_descuento": _fmt_dec("0"),
            "valor_total_descuento": _fmt_dec("0")
        }
    ]
    valor_nc = {
        "valor_base": _fmt_dec("4992000"),
        "valor_base_calculo_impuestos": _fmt_dec("0"),
        "valor_base_mas_impuestos": _fmt_dec("4992000"),
        "valor_anticipo": _fmt_dec("0"),
        "valor_descuento_total": _fmt_dec("0"),
        "valor_total_recargos": _fmt_dec("0"),
        "valor_total_impuesto_1": _fmt_dec("0"),
        "valor_total_impuesto_2": _fmt_dec("0"),
        "valor_total_impuesto_3": _fmt_dec("0"),
        "valor_total_impuesto_4": _fmt_dec("0"),
        "valor_total_reteiva": _fmt_dec("0"),
        "valor_total_retefuente": _fmt_dec("0"),
        "valor_total_reteica": _fmt_dec("0"),
        "total_nota_credito": _fmt_dec("4992000"),
        "valor_total_a_pagar": _fmt_dec("4992000")
    }
    generalidades = {
        "tipo_ambiente_dian": "2",  # 1=Prod, 2=Pruebas
        "version": "1",
        "identificador_transmision": "PKG-NC-23349",
        "rg_tipo": "PDF",           # o HTML / PDF_PROPIO
        "rg_base_64": "UEsDBAoAAAAAA...",  # TODO: PDF en base64 (si aplica)
        "rg_px_qr": {"x":"10","y":"10","size":"10","mostrar_en":"PRIMERA_PAGINA"},
        "rg_px_cufe": {"x":"10","y":"35","size":"10","mostrar_en":"PRIMERA_PAGINA"},
        "integrador": {"nombre":"ERP-XXXX","tipo":"ERP","webhook":""}
    }

    payload = construir_payload_nota_credito(
        documento_obligado=documento_obligado,
        encabezado=encabezado,
        servicio=servicio,
        informacion_documento=informacion_documento,
        detalle_factura=detalle_factura,
        impuestos=impuestos,
        descuentos=descuentos,
        valor_nota_credito=valor_nc,
        generalidades=generalidades,
        # opcionales:
        formas_de_pago=[{"metodo_de_pago": "1", "tipo_de_pago": "10", "identificador_de_pago": "", "fecha_vencimiento": ""}],
        retenciones=[{"codigo":"0","porcentaje":_fmt_dec("0.00"),"valor_base":_fmt_dec("0"),"valor_retenido":_fmt_dec("0")}],
        recargos=[],
        cambio_de_moneda=None,
        cambio_de_moneda_totales=None,
        entrega_de_bienes=None,
        informacion_adquiriente={
            "tipo_contribuyente":"1", "tipo_regimen":"2","tipo_identificacion":"31","identificacion":"830053105",
            "correo_electronico":"tesoreria@cliente.com",
            "numero_movil":"", "nombre":{"razon_social":"CLIENTE DEMO","primer_nombre":"","segundo_nombre":"","apellido":""},
            "pais":"CO","departamento":"11","ciudad":"11001","direccion":"Calle 123 # 45-67",
            "RUT":{"resp_calidades_atributos":["O-11","R-99-PN"],"usuario_aduanero":[]},
            "detalles_tributarios":"ZZ"
        }
    )

    print("JSON listo para enviar:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    # ====== Envío a PRUEBAS ======
    url = "https://servicios-pruebas.afacturar.com/api/doc_equivalente/TTP/nota_credito"
    token = "Bearer TU_TOKEN_AQUI"   # TODO: reemplaza por el token real
    headers = {
        "Accept": "application/json",
        "Authorization": token,
        "Content-Type": "application/json"
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    print("Status:", resp.status_code)
    try:
        print("Respuesta:", resp.json())
    except Exception:
        print("Texto:", resp.text)

if __name__ == "__main__":
    ejemplo_construccion_y_envio()
