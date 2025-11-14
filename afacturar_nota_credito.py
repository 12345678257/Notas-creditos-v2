# afacturar_nota_credito.py
from __future__ import annotations
import json
import re
from typing import Dict, Any, List, Optional

# ==========================
# Helpers de formato/validación
# ==========================

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
_TIME_HM_RE = re.compile(r"^\d{2}:\d{2}$")
_DEC_RE = re.compile(r"^\d+(\.\d{1,2})?$")  # string con punto y hasta 2 decimales

def _fmt_dec(val: float | int | str, dec: int = 2) -> str:
    """
    A decimal string (con .) y 'dec' decimales.
    Acepta strings con coma y normaliza.
    """
    if isinstance(val, str):
        s = val.strip().replace(",", ".")
        try:
            num = float(s)
        except Exception:
            raise ValueError(f"Valor numérico inválido: {val}")
    else:
        num = float(val)
    return f"{num:.{dec}f}"

def _sanitize_text(s: Any, min_len: int = 0) -> str:
    if s is None:
        s = ""
    s = str(s)
    s = re.sub(r"[\r\n\t]+", " ", s)
    s = re.sub(r"\s{2,}", " ", s).strip()
    if min_len and len(s) < min_len:
        s += " " * (min_len - len(s))
    return s

def _nota_to_single_quote_string(nota_dict: Dict[str, Any]) -> str:
    """
    Convierte dict -> "{'k1':'v1','k2':'v2'}" (comillas simples) como exige Afacturar.
    """
    parts = []
    for k, v in nota_dict.items():
        key = str(k).replace("'", " ")
        if isinstance(v, (dict, list)):
            v_str = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
        else:
            v_str = str(v)
        v_str = v_str.replace("\\'", " ").replace("\\", " ").replace("'", " ")
        v_str = _sanitize_text(v_str)
        parts.append(f"'{key}':'{v_str}'")
    return "{" + ",".join(parts) + "}"

def _split_nota_string(nota_str: str, max_len: int = 1000, min_piece: int = 15) -> List[str]:
    nota_str = _sanitize_text(nota_str)
    if not nota_str:
        nota_str = "{'OBS':'Sin observación'}"
    chunks = [nota_str[i:i+max_len] for i in range(0, len(nota_str), max_len)] or [nota_str]
    if len(chunks[-1]) < min_piece and len(chunks) > 1:
        chunks[-2] += chunks[-1]
        chunks.pop()
    if len(chunks) == 1 and len(chunks[0]) < min_piece:
        chunks[0] += " " * (min_piece - len(chunks[0]))
    return chunks

# ==========================
# Validadores de negocio (enums / formatos)
# ==========================

def _assert_date(d: str, field: str):
    if not _DATE_RE.match(d or ""):
        raise ValueError(f"{field} debe ser AAAA-MM-DD")

def _assert_time_hms(t: str, field: str):
    if not _TIME_RE.match(t or ""):
        raise ValueError(f"{field} debe ser HH:MM:SS")

def _assert_time_hm(t: str, field: str):
    if not _TIME_HM_RE.match(t or ""):
        raise ValueError(f"{field} debe ser HH:MM")

def _assert_enum(val: str, field: str, allowed: List[str]):
    if str(val) not in allowed:
        raise ValueError(f"{field} inválido. Permitidos: {allowed}")

def _assert_decimal_string(s: str, field: str):
    if not _DEC_RE.match(s or ""):
        raise ValueError(f"{field} debe ser número con punto y hasta 2 decimales (p.ej. 1234.56)")

# ==========================
# Constructor principal
# ==========================

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
    Devuelve:
    {
      "documento_obligado": "...",
      "data": { "nota_credito": [ {...} ], "generalidades": {...} }
    }
    Cumple el layout y reglas clave del endpoint de Afacturar.
    """

    # -------- Encabezado requerido --------
    req = ["id_nota_credito", "fecha", "hora", "moneda", "tipo_operacion", "tipo_nota_credito"]
    for k in req:
        if k not in encabezado or _sanitize_text(encabezado[k]) == "":
            raise ValueError(f"encabezado.{k} es requerido")

    _assert_date(encabezado["fecha"], "encabezado.fecha")
    _assert_time_hms(encabezado["hora"], "encabezado.hora")
    _assert_enum(str(encabezado["tipo_operacion"]), "encabezado.tipo_operacion", ["35"])
    _assert_enum(str(encabezado["tipo_nota_credito"]), "encabezado.tipo_nota_credito", ["1", "2", "3", "4", "5"])

    # 'nota' → array de strings
    if "nota" in encabezado and encabezado["nota"]:
        if isinstance(encabezado["nota"], list):
            base = "".join(str(x) for x in encabezado["nota"])
            nota_str = _sanitize_text(base)
        else:
            nota_str = _sanitize_text(str(encabezado["nota"]))
    else:
        nota_str = _nota_to_single_quote_string({
            "MOTIVO": "Nota crédito parcial por ajuste de precio",
            "SOPORTE": "Glosa parcial sobre servicios",
            "OBS": f"NC {encabezado.get('id_nota_credito','')}"
        })
    nota_partes = _split_nota_string(nota_str, max_len=1000, min_piece=15)

    # -------- Servicio mínimo requerido --------
    if "modo_transporte" not in servicio or "lugar_origen" not in servicio or \
       "lugar_destino" not in servicio or "hora_salida" not in servicio or \
       "datos_vehiculo" not in servicio:
        raise ValueError("servicio requiere modo_transporte, lugar_origen, lugar_destino, hora_salida y datos_vehiculo")

    _assert_enum(str(servicio["modo_transporte"]), "servicio.modo_transporte", ["TERRESTRE"])
    _assert_time_hm(servicio["hora_salida"], "servicio.hora_salida")
    dv = servicio.get("datos_vehiculo", {})
    if "codigo" not in dv or "placa" not in dv or "tipo" not in dv:
        raise ValueError("servicio.datos_vehiculo requiere codigo, placa y tipo")
    _assert_enum(str(dv["tipo"]), "servicio.datos_vehiculo.tipo", ["AUTOBUS", "MICROBUS", "BUS"])

    # -------- Documento afectado --------
    for k in ["id_documento", "fecha", "hora"]:
        if k not in informacion_documento:
            raise ValueError(f"informacion_documento.{k} es requerido")
    _assert_date(informacion_documento["fecha"], "informacion_documento.fecha")
    _assert_time_hms(informacion_documento["hora"], "informacion_documento.hora")

    # CUDE puede venir como codigo_unico_documento o codigo_unico_factura
    cude = informacion_documento.get("codigo_unico_documento", informacion_documento.get("codigo_unico_factura", ""))
    if not _sanitize_text(cude):
        raise ValueError("informacion_documento requiere codigo_unico_documento (CUDE)")

    # -------- Detalle (al menos 1 línea) --------
    if not isinstance(detalle_factura, list) or not detalle_factura:
        raise ValueError("detalle_factura debe contener al menos una línea")

    # Normalización rápida de decimales de cada línea
    for it in detalle_factura:
        # cantidad puede ser numérico
        if "valor_unitario" in it:
            it["valor_unitario"] = _fmt_dec(it["valor_unitario"])
        if "valor_total_detalle" in it:
            it["valor_total_detalle"] = _fmt_dec(it["valor_total_detalle"])
        if "valor_total_detalle_con_cargo_descuento" in it:
            it["valor_total_detalle_con_cargo_descuento"] = _fmt_dec(it["valor_total_detalle_con_cargo_descuento"])

    # -------- Impuestos / Descuentos --------
    if not isinstance(impuestos, list) or not impuestos:
        raise ValueError("impuestos requiere al menos 1 ítem")
    if not isinstance(descuentos, list) or not descuentos:
        raise ValueError("descuentos requiere al menos 1 ítem")

    # -------- Totales (obligatorios) --------
    def _norm_totales(d: Dict[str, Any], keys: List[str]) -> Dict[str, Any]:
        nd = dict(d)
        for k in keys:
            if k in nd and nd[k] not in (None, ""):
                nd[k] = _fmt_dec(nd[k], 2)
        return nd

    valor_nota_credito = _norm_totales(
        valor_nota_credito,
        [
            "valor_base","valor_base_calculo_impuestos","valor_base_mas_impuestos",
            "valor_anticipo","valor_descuento_total","valor_total_recargos",
            "valor_total_impuesto_1","valor_total_impuesto_2","valor_total_impuesto_3","valor_total_impuesto_4",
            "valor_total_reteiva","valor_total_retefuente","valor_total_reteica",
            "total_nota_credito","valor_total_a_pagar"
        ]
    )

    # valida los dos obligatorios clave:
    _assert_decimal_string(valor_nota_credito.get("total_nota_credito",""), "valor_nota_credito.total_nota_credito")
    _assert_decimal_string(valor_nota_credito.get("valor_total_a_pagar",""), "valor_nota_credito.valor_total_a_pagar")

    if cambio_de_moneda_totales:
        cambio_de_moneda_totales = _norm_totales(
            cambio_de_moneda_totales,
            [
                "valor_base","valor_base_calculo_impuestos","valor_base_mas_impuestos",
                "valor_anticipo","valor_descuento_total","valor_total_recargos",
                "valor_total_impuesto_1","valor_total_impuesto_2","valor_total_impuesto_3","valor_total_impuesto_4",
                "valor_total_reteiva","valor_total_retefuente","valor_total_reteica",
                "total_nota_credito","valor_total_a_pagar"
            ]
        )

    # -------- Generalidades --------
    if "tipo_ambiente_dian" not in generalidades or "version" not in generalidades or \
       "identificador_transmision" not in generalidades or "rg_tipo" not in generalidades:
        raise ValueError("generalidades requiere tipo_ambiente_dian, version, identificador_transmision y rg_tipo")

    _assert_enum(str(generalidades["tipo_ambiente_dian"]), "generalidades.tipo_ambiente_dian", ["1", "2"])
    _assert_enum(str(generalidades["rg_tipo"]), "generalidades.rg_tipo", ["HTML", "PDF", "PDF_PROPIO"])

    # -------- Armar objeto principal --------
    data_nc: Dict[str, Any] = {
        "encabezado": {
            "id_nota_credito": _sanitize_text(encabezado["id_nota_credito"]),
            "fecha": _sanitize_text(encabezado["fecha"]),
            "hora": _sanitize_text(encabezado["hora"]),
            "nota": nota_partes,
            "moneda": _sanitize_text(encabezado["moneda"]),
            "tipo_operacion": _sanitize_text(encabezado["tipo_operacion"]),
            "tipo_nota_credito": _sanitize_text(encabezado["tipo_nota_credito"]),
            "numero_orden": _sanitize_text(encabezado.get("numero_orden","")),
            "prefijo": _sanitize_text(encabezado.get("prefijo","")),
        },
        "servicio": servicio,
        "informacion_documento": {
            "id_documento": _sanitize_text(informacion_documento.get("id_documento","")),
            "codigo_unico_documento": _sanitize_text(cude),
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
        # si viene, validar formato base
        if "fecha_cambio" in cambio_de_moneda:
            _assert_date(cambio_de_moneda["fecha_cambio"], "cambio_de_moneda.fecha_cambio")
        data_nc["cambio_de_moneda"] = cambio_de_moneda
    if retenciones:
        data_nc["retenciones"] = retenciones
    if recargos:
        data_nc["recargos"] = recargos
    if cambio_de_moneda_totales:
        data_nc["cambio_de_moneda_totales"] = cambio_de_moneda_totales
    if entrega_de_bienes:
        # si viene, validar hora ISO opcional
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
