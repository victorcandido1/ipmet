"""
state_manager.py - Gerenciamento centralizado de estado
Módulo para persistência e migração de estados do sistema REVO
"""

import os
import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Set


class StateManager:
    """Gerenciador centralizado de estados do sistema"""
    
    STATE_DIR = '.state'
    
    TELEGRAM_STATE = 'telegram.json'
    WEATHER_STATE = 'weather_alerts.json'
    PROACTIVE_STATE = 'proactive_alerts.json'
    
    LEGACY_TELEGRAM = 'telegram_state.json'
    LEGACY_WEATHER = 'weather_alerts_state.json'
    LEGACY_PROACTIVE = 'proactive_alerts_state.json'
    
    def __init__(self, base_dir: str = None):
        """Inicializa o gerenciador de estado"""
        self.base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
        self.state_dir = os.path.join(self.base_dir, self.STATE_DIR)
        
        os.makedirs(self.state_dir, exist_ok=True)
        
        self._migrate_legacy_states()
    
    def _get_state_path(self, filename: str) -> str:
        """Retorna caminho completo do arquivo de estado"""
        return os.path.join(self.state_dir, filename)
    
    def _get_legacy_path(self, filename: str) -> str:
        """Retorna caminho de arquivo legado na raiz"""
        return os.path.join(self.base_dir, filename)
    
    def _migrate_legacy_states(self):
        """Migra arquivos de estado antigos para nova estrutura"""
        migrations = [
            (self.LEGACY_TELEGRAM, self.TELEGRAM_STATE),
            (self.LEGACY_WEATHER, self.WEATHER_STATE),
            (self.LEGACY_PROACTIVE, self.PROACTIVE_STATE),
        ]
        
        for legacy_name, new_name in migrations:
            legacy_path = self._get_legacy_path(legacy_name)
            new_path = self._get_state_path(new_name)
            
            if os.path.exists(legacy_path) and not os.path.exists(new_path):
                try:
                    with open(legacy_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    with open(new_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    logging.info(f"Estado migrado: {legacy_name} -> .state/{new_name}")
                except Exception as e:
                    logging.warning(f"Erro ao migrar {legacy_name}: {e}")
    
    def _load_state(self, filename: str, default: Any = None) -> Any:
        """Carrega estado de arquivo JSON"""
        if default is None:
            default = {}
        
        filepath = self._get_state_path(filename)
        legacy_path = self._get_legacy_path(filename.replace('.json', '_state.json'))
        
        for path in [filepath, legacy_path]:
            if os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        return json.load(f)
                except (json.JSONDecodeError, IOError):
                    continue
        
        return default
    
    def _save_state(self, filename: str, data: Any) -> bool:
        """Salva estado em arquivo JSON"""
        filepath = self._get_state_path(filename)
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except (IOError, TypeError) as e:
            logging.error(f"Erro ao salvar estado {filename}: {e}")
            return False
    
    @property
    def telegram_state_file(self) -> str:
        """Caminho do arquivo de estado do Telegram"""
        return self._get_state_path(self.TELEGRAM_STATE)
    
    @property
    def weather_state_file(self) -> str:
        """Caminho do arquivo de estado meteorológico"""
        return self._get_state_path(self.WEATHER_STATE)
    
    @property
    def proactive_state_file(self) -> str:
        """Caminho do arquivo de estado proativo"""
        return self._get_state_path(self.PROACTIVE_STATE)
    
    def load_telegram_state(self) -> Dict:
        """Carrega estado de voos notificados"""
        return self._load_state(self.TELEGRAM_STATE, {
            'voos_notificados': [],
            'last_update': None
        })
    
    def save_telegram_state(self, data: Dict) -> bool:
        """Salva estado de voos notificados"""
        data['last_update'] = datetime.now().isoformat()
        return self._save_state(self.TELEGRAM_STATE, data)
    
    def load_weather_state(self, max_age_hours: float = 2) -> Set[str]:
        """Carrega estado de alertas meteorológicos"""
        data = self._load_state(self.WEATHER_STATE, {})
        
        last_check = data.get('last_check', '')
        if last_check:
            try:
                last_dt = datetime.fromisoformat(last_check)
                hours_diff = (datetime.now() - last_dt).total_seconds() / 3600
                if hours_diff < max_age_hours:
                    return set(data.get('alerts', []))
            except:
                pass
        
        return set()
    
    def save_weather_state(self, alerts: Set[str]) -> bool:
        """Salva estado de alertas meteorológicos"""
        data = {
            'alerts': list(alerts),
            'last_check': datetime.now().isoformat()
        }
        return self._save_state(self.WEATHER_STATE, data)
    
    def load_proactive_state(self) -> Dict:
        """Carrega estado de alertas proativos"""
        data = self._load_state(self.PROACTIVE_STATE, {})
        return data.get('last_alerts', {})
    
    def save_proactive_state(self, alerts: Dict) -> bool:
        """Salva estado de alertas proativos"""
        data = {
            'last_alerts': alerts,
            'last_check': datetime.now().isoformat()
        }
        return self._save_state(self.PROACTIVE_STATE, data)
    
    def cleanup_legacy_files(self, dry_run: bool = True) -> list:
        """Remove arquivos de estado legados após migração"""
        legacy_files = [
            self.LEGACY_TELEGRAM,
            self.LEGACY_WEATHER,
            self.LEGACY_PROACTIVE,
        ]
        
        removed = []
        for filename in legacy_files:
            legacy_path = self._get_legacy_path(filename)
            if os.path.exists(legacy_path):
                if dry_run:
                    removed.append(legacy_path)
                else:
                    try:
                        os.remove(legacy_path)
                        removed.append(legacy_path)
                        logging.info(f"Arquivo legado removido: {filename}")
                    except Exception as e:
                        logging.warning(f"Erro ao remover {filename}: {e}")
        
        return removed


_manager_instance: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    """Obtém instância singleton do StateManager"""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = StateManager()
    return _manager_instance


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("StateManager - Teste de migração e estado")
    print("=" * 50)
    
    manager = StateManager()
    
    print(f"\nDiretório de estados: {manager.state_dir}")
    print(f"Telegram state: {manager.telegram_state_file}")
    print(f"Weather state: {manager.weather_state_file}")
    print(f"Proactive state: {manager.proactive_state_file}")
    
    legacy = manager.cleanup_legacy_files(dry_run=True)
    if legacy:
        print(f"\nArquivos legados encontrados (dry run):")
        for f in legacy:
            print(f"  - {f}")
    else:
        print("\nNenhum arquivo legado encontrado")
    
    print("\nEstados carregados:")
    print(f"  Telegram: {len(manager.load_telegram_state().get('voos_notificados', []))} voos")
    print(f"  Weather: {len(manager.load_weather_state())} alertas")
    print(f"  Proactive: {len(manager.load_proactive_state())} alertas")
