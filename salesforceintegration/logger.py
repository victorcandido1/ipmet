"""
logger.py - Configuração centralizada de logging
Módulo para configuração uniforme de logs em todo o sistema REVO
"""

import logging
import os
from datetime import datetime


LOG_DIR = '.logs'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def setup_logging(
    name: str = 'revo',
    level: int = logging.INFO,
    log_to_file: bool = True,
    log_file: str = None
) -> logging.Logger:
    """
    Configura e retorna um logger com handlers padronizados.
    
    Args:
        name: Nome do logger
        level: Nível de logging (default: INFO)
        log_to_file: Se deve salvar em arquivo
        log_file: Nome do arquivo de log (default: {name}.log)
    
    Returns:
        Logger configurado
    """
    logger = logging.getLogger(name)
    
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    logger.propagate = False
    
    formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    if log_to_file:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(base_dir, LOG_DIR)
        os.makedirs(log_dir, exist_ok=True)
        
        if log_file is None:
            log_file = f"{name}.log"
        
        log_path = os.path.join(log_dir, log_file)
        
        file_handler = logging.FileHandler(log_path, encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str = 'revo') -> logging.Logger:
    """Obtém logger existente ou cria um novo com configuração padrão"""
    logger = logging.getLogger(name)
    
    if not logger.handlers:
        return setup_logging(name)
    
    return logger


class LogContext:
    """Context manager para logging de operações com tempo"""
    
    def __init__(self, logger: logging.Logger, operation: str):
        self.logger = logger
        self.operation = operation
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        self.logger.info(f"Iniciando: {self.operation}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.now() - self.start_time).total_seconds()
        if exc_type:
            self.logger.error(f"Falha em {self.operation} após {duration:.2f}s: {exc_val}")
        else:
            self.logger.info(f"Concluído: {self.operation} ({duration:.2f}s)")
        return False


if __name__ == "__main__":
    logger = setup_logging('test')
    logger.info("Teste de logging")
    logger.warning("Aviso de teste")
    logger.error("Erro de teste")
    
    with LogContext(logger, "operação de teste"):
        import time
        time.sleep(0.5)
    
    print(f"\nArquivo de log criado em: .logs/test.log")
