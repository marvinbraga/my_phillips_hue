"""
Configuração centralizada de logging para o Marvin Hue usando Loguru.
Fornece loggers estruturados com rotação automática de arquivos.
"""

import sys
from pathlib import Path

from loguru import logger


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
) -> None:
    """
    Configura o sistema de logging principal usando Loguru.

    Args:
        log_level: Nível de log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Caminho do arquivo de log
        max_bytes: Tamanho máximo do arquivo antes de rotacionar (padrão: 10MB)
        backup_count: Número de arquivos de backup (padrão: 5)
        console_output: Se True, também imprime logs no console
    """
    # Remove todos os handlers padrão
    logger.remove()

    # Cria diretório de logs se não existir
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Handler de arquivo com rotação
    logger.add(
        log_path,
        level="DEBUG",  # Arquivo captura tudo
        rotation=max_bytes,
        retention=backup_count,
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} - {name} - {level} - {message}",
        backtrace=True,
        # diagnose=False: NÃO renderizar valores de variáveis locais nos
        # tracebacks gravados em disco — frame-locals dos providers contêm
        # api_key (e mensagens do usuário). backtrace=True mantém o traceback.
        diagnose=False,
    )

    # Handler de console (opcional)
    if console_output:
        logger.add(
            sys.stdout,
            level=log_level.upper(),
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> - <level>{level}</level> - {message}",
            colorize=True,
        )

    logger.info(f"Sistema de logging iniciado (nível: {log_level})")


def get_logger(module_name: str):
    """
    Retorna um logger para um módulo específico.

    Args:
        module_name: Nome do módulo (ex: 'controllers', 'screen_mirror')

    Returns:
        Logger configurado para o módulo (loguru logger)
    """
    # Loguru usa um logger global, então apenas retornamos o logger
    # com o contexto do módulo
    return logger.bind(name=f"marvin_hue.{module_name}")


def log_exception(message: str, exc_info: bool = True) -> None:
    """
    Loga uma exceção com traceback completo.

    Args:
        message: Mensagem descritiva do erro
        exc_info: Se True, inclui traceback completo (sempre True no loguru)
    """
    if exc_info:
        logger.exception(message)
    else:
        logger.error(message)


# Configurar logging no import do módulo usando settings se disponível
_settings = _get_settings()
if _settings:
    setup_logging(log_level=_settings.log_level, log_file=_settings.log_file)
else:
    setup_logging()  # Usa valores padrão
