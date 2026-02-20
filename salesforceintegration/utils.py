"""
utils.py - Funções utilitárias compartilhadas
Módulo central para funções comuns usadas em todo o projeto REVO
"""

import json
import os
from datetime import datetime
from typing import Any, Optional


def format_currency(value: float) -> str:
    """Formata valores monetários no padrão brasileiro"""
    try:
        return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ 0,00"


def format_number(value: float) -> str:
    """Formata números inteiros com separador de milhar"""
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def format_datetime_br(dt: datetime) -> str:
    """Formata datetime no padrão brasileiro DD/MM/YYYY HH:MM"""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except:
            return dt
    if isinstance(dt, datetime):
        return dt.strftime("%d/%m/%Y %H:%M")
    return str(dt)


def format_date_br(dt: datetime) -> str:
    """Formata data no padrão brasileiro DD/MM/YYYY"""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        except:
            return dt
    if isinstance(dt, datetime):
        return dt.strftime("%d/%m/%Y")
    return str(dt)


def load_json_state(filepath: str, default: Any = None) -> Any:
    """Carrega estado de um arquivo JSON com fallback seguro"""
    if default is None:
        default = {}
    try:
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return default
    except (json.JSONDecodeError, IOError) as e:
        return default


def save_json_state(filepath: str, data: Any) -> bool:
    """Salva estado em arquivo JSON com tratamento de erro"""
    try:
        os.makedirs(os.path.dirname(filepath) if os.path.dirname(filepath) else '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except (IOError, TypeError) as e:
        return False


def safe_get(data: dict, *keys, default: Any = None) -> Any:
    """Acesso seguro a chaves aninhadas em dicionários"""
    result = data
    for key in keys:
        try:
            result = result[key]
        except (KeyError, TypeError, IndexError):
            return default
    return result


def parse_iso_datetime(dt_str: str) -> Optional[datetime]:
    """Parse de string ISO para datetime com tratamento de erro"""
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None
