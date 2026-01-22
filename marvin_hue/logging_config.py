"""
Configuração centralizada de logging para o Marvin Hue.
Fornece loggers estruturados com rotação automática de arquivos.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict


# Formato de log com timestamp
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Cache de loggers
_loggers: Dict[str, logging.Logger] = {}


def _get_settings():
    """
    Importa settings de forma lazy para evitar circular imports.

    Returns:
        Settings object ou None se não disponível
    """
    try:
        from marvin_hue.config import settings

        return settings
    except ImportError:
        return None


def setup_logging(
    log_level: str = "INFO",
    log_file: str = "logs/marvin_hue.log",
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    console_output: bool = True,
) -> logging.Logger:
    """
    Configura o sistema de logging principal.

    Args:
        log_level: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Caminho do arquivo de log
        max_bytes: Tamanho máximo do arquivo antes de rotacionar (padrão: 10MB)
        backup_count: Número de arquivos de backup (padrão: 5)
        console_output: Se True, também imprime logs no console

    Returns:
        Logger configurado para o módulo raiz
    """
    # Configura o logger raiz
    root_logger = logging.getLogger("marvin_hue")
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove handlers existentes para evitar duplicação
    root_logger.handlers.clear()

    # Formatter
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    # Handler de arquivo com rotação
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)  # Arquivo captura tudo
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Handler de console (opcional)
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    root_logger.info(f"Sistema de logging iniciado (nível: {log_level})")
    return root_logger


def get_logger(module_name: str) -> logging.Logger:
    """
    Retorna um logger para um módulo específico.

    Args:
        module_name: Nome do módulo (ex: 'controllers', 'screen_mirror')

    Returns:
        Logger configurado para o módulo
    """
    full_name = f"marvin_hue.{module_name}"

    if full_name not in _loggers:
        logger = logging.getLogger(full_name)
        # Herda configuração do logger raiz
        _loggers[full_name] = logger

    return _loggers[full_name]


def log_exception(logger: logging.Logger, message: str, exc_info: bool = True) -> None:
    """
    Loga uma exceção com traceback completo.

    Args:
        logger: Logger a ser usado
        message: Mensagem descritiva do erro
        exc_info: Se True, inclui traceback completo
    """
    logger.error(message, exc_info=exc_info)


# Configurar logging no import do módulo usando settings se disponível
# Pode ser sobrescrito chamando setup_logging() novamente
_settings = _get_settings()
if _settings:
    setup_logging(log_level=_settings.log_level, log_file=_settings.log_file)
else:
    setup_logging()  # Usa valores padrão
