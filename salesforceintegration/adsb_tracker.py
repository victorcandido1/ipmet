"""
ADS-B Tracker para helicópteros da frota REVO
Usa OpenSky Network API (gratuita) para rastrear posição em tempo real
"""
import requests
import logging
from datetime import datetime
from typing import Optional, Dict, List, Tuple

OPENSKY_API_BASE = "https://opensky-network.org/api"

FROTA_HELICOPTEROS = {
    'PR-OMB': {
        'icao24': 'e485c5',  # Eurocopter EC155B1 / H155
        'tipo': 'EC155 / H155',
        'modelo': 'EC155B1',
        'cor': '#1E88E5'
    },
    'PR-OMH': {
        'icao24': 'e485b5',  # Eurocopter EC155B1 (estimado baseado em sequência)
        'tipo': 'EC155 / H155',
        'modelo': 'EC155B1',
        'cor': '#43A047'
    },
    'PR-OOE': {
        'icao24': 'e48c9b',  # Airbus H135 (estimado)
        'tipo': 'EC135 / H135',
        'modelo': 'H135',
        'cor': '#FB8C00'
    }
}

class ADSBTracker:
    """Rastreador ADS-B usando OpenSky Network API"""
    
    def __init__(self, username: str = None, password: str = None):
        """
        Inicializa o tracker
        
        Args:
            username: Usuário OpenSky (opcional, aumenta rate limit de 400 para 4000/dia)
            password: Senha OpenSky
        """
        self.auth = (username, password) if username and password else None
        self.session = requests.Session()
        
    def get_aircraft_state(self, icao24: str) -> Optional[Dict]:
        """
        Busca estado atual de uma aeronave pelo ICAO24
        
        Args:
            icao24: Código ICAO24 hex da aeronave (6 caracteres)
            
        Returns:
            Dict com estado da aeronave ou None se não encontrada/offline
        """
        try:
            url = f"{OPENSKY_API_BASE}/states/all"
            params = {'icao24': icao24.lower()}
            
            response = self.session.get(url, params=params, auth=self.auth, timeout=10)
            
            if response.status_code == 429:
                logging.warning("OpenSky API: Rate limit atingido")
                return None
                
            response.raise_for_status()
            data = response.json()
            
            if not data.get('states'):
                return None
                
            state = data['states'][0]
            return self._parse_state_vector(state)
            
        except requests.RequestException as e:
            logging.error(f"Erro ao consultar OpenSky: {e}")
            return None
            
    def _parse_state_vector(self, state: list) -> Dict:
        """
        Converte state vector da API para dicionário legível
        
        State vector indices:
        0: icao24
        1: callsign
        2: origin_country
        3: time_position
        4: last_contact
        5: longitude
        6: latitude
        7: baro_altitude (metros)
        8: on_ground
        9: velocity (m/s)
        10: true_track (graus, norte=0)
        11: vertical_rate (m/s)
        12: sensors
        13: geo_altitude (metros)
        14: squawk
        15: spi
        16: position_source (0=ADS-B, 1=ASTERIX, 2=MLAT, 3=FLARM)
        17: category (categoria da aeronave)
        """
        return {
            'icao24': state[0],
            'callsign': (state[1] or '').strip(),
            'origin_country': state[2],
            'time_position': datetime.fromtimestamp(state[3]) if state[3] else None,
            'last_contact': datetime.fromtimestamp(state[4]) if state[4] else None,
            'longitude': state[5],
            'latitude': state[6],
            'altitude_baro': state[7],
            'on_ground': state[8],
            'velocity_ms': state[9],
            'velocity_kmh': round(state[9] * 3.6, 1) if state[9] else None,
            'velocity_kts': round(state[9] * 1.944, 1) if state[9] else None,
            'track': state[10],
            'vertical_rate': state[11],
            'altitude_geo': state[13],
            'squawk': state[14],
            'position_source': ['ADS-B', 'ASTERIX', 'MLAT', 'FLARM'][state[16]] if state[16] is not None else 'Unknown'
        }
        
    def get_fleet_status(self) -> Dict[str, Optional[Dict]]:
        """
        Busca status de toda a frota de helicópteros
        
        Returns:
            Dict com prefixo -> estado ou None para cada aeronave
        """
        all_icao24 = [info['icao24'] for info in FROTA_HELICOPTEROS.values()]
        
        try:
            url = f"{OPENSKY_API_BASE}/states/all"
            params = [('icao24', icao) for icao in all_icao24]
            
            response = self.session.get(url, params=params, auth=self.auth, timeout=15)
            
            if response.status_code == 429:
                logging.warning("OpenSky API: Rate limit atingido")
                return {prefix: None for prefix in FROTA_HELICOPTEROS}
                
            response.raise_for_status()
            data = response.json()
            
            results = {prefix: None for prefix in FROTA_HELICOPTEROS}
            
            if data.get('states'):
                icao_to_prefix = {v['icao24']: k for k, v in FROTA_HELICOPTEROS.items()}
                
                for state in data['states']:
                    icao24 = state[0]
                    if icao24 in icao_to_prefix:
                        prefix = icao_to_prefix[icao24]
                        results[prefix] = self._parse_state_vector(state)
                        results[prefix]['prefixo'] = prefix
                        results[prefix]['tipo'] = FROTA_HELICOPTEROS[prefix]['tipo']
                        
            return results
            
        except requests.RequestException as e:
            logging.error(f"Erro ao consultar OpenSky: {e}")
            return {prefix: None for prefix in FROTA_HELICOPTEROS}
            
    def is_aircraft_flying(self, prefixo: str) -> Tuple[bool, Optional[Dict]]:
        """
        Verifica se uma aeronave está voando
        
        Args:
            prefixo: Prefixo da aeronave (ex: PR-OMB)
            
        Returns:
            Tupla (está_voando, dados_voo ou None)
        """
        if prefixo not in FROTA_HELICOPTEROS:
            return False, None
            
        icao24 = FROTA_HELICOPTEROS[prefixo]['icao24']
        state = self.get_aircraft_state(icao24)
        
        if not state:
            return False, None
            
        is_flying = not state.get('on_ground', True)
        return is_flying, state
        
    def get_flying_aircraft(self) -> List[Dict]:
        """
        Retorna lista de aeronaves da frota que estão voando no momento
        
        Returns:
            Lista de dicts com dados de voo
        """
        fleet_status = self.get_fleet_status()
        flying = []
        
        for prefixo, state in fleet_status.items():
            if state and not state.get('on_ground', True):
                state['prefixo'] = prefixo
                flying.append(state)
                
        return flying

    def format_flight_status(self, state: Dict) -> str:
        """
        Formata status de voo para mensagem de texto
        
        Args:
            state: Dicionário retornado por get_aircraft_state
            
        Returns:
            String formatada com informações do voo
        """
        if not state:
            return "Aeronave não detectada (pode estar em solo ou fora de cobertura)"
            
        lines = []
        
        prefixo = state.get('prefixo', state.get('callsign', 'N/A'))
        lines.append(f"Aeronave: {prefixo}")
        
        if state.get('on_ground'):
            lines.append("Status: Em Solo")
        else:
            lines.append("Status: EM VOO")
            
        if state.get('latitude') and state.get('longitude'):
            lines.append(f"Posicao: {state['latitude']:.4f}, {state['longitude']:.4f}")
            
        if state.get('altitude_baro'):
            alt_ft = round(state['altitude_baro'] * 3.281)
            lines.append(f"Altitude: {alt_ft} ft ({round(state['altitude_baro'])} m)")
            
        if state.get('velocity_kts'):
            lines.append(f"Velocidade: {state['velocity_kts']} kts ({state['velocity_kmh']} km/h)")
            
        if state.get('track') is not None:
            direcoes = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
            idx = int((state['track'] + 22.5) / 45) % 8
            lines.append(f"Proa: {round(state['track'])} ({direcoes[idx]})")
            
        if state.get('vertical_rate'):
            vr = state['vertical_rate']
            if vr > 0:
                lines.append(f"Razao: +{round(vr * 196.85)} ft/min (subindo)")
            elif vr < 0:
                lines.append(f"Razao: {round(vr * 196.85)} ft/min (descendo)")
                
        if state.get('position_source'):
            lines.append(f"Fonte: {state['position_source']}")
            
        if state.get('last_contact'):
            lines.append(f"Atualizado: {state['last_contact'].strftime('%H:%M:%S')}")
            
        return '\n'.join(lines)


def test_adsb_tracker():
    """Testa o tracker ADS-B"""
    print("=" * 50)
    print("TESTE ADS-B TRACKER - FROTA REVO")
    print("=" * 50)
    
    tracker = ADSBTracker()
    
    print("\n1. Verificando status da frota...")
    fleet = tracker.get_fleet_status()
    
    for prefixo, state in fleet.items():
        print(f"\n--- {prefixo} ---")
        if state:
            print(tracker.format_flight_status(state))
        else:
            print(f"Nao detectado (ICAO24: {FROTA_HELICOPTEROS[prefixo]['icao24']})")
            print("Pode estar em solo, fora de cobertura ADS-B, ou ICAO24 incorreto")
    
    print("\n2. Aeronaves voando agora:")
    flying = tracker.get_flying_aircraft()
    
    if flying:
        for aircraft in flying:
            print(f"\n  {aircraft.get('prefixo')} - EM VOO")
            print(f"    Altitude: {aircraft.get('altitude_baro', 'N/A')} m")
            print(f"    Velocidade: {aircraft.get('velocity_kts', 'N/A')} kts")
    else:
        print("  Nenhuma aeronave da frota detectada em voo")
        
    print("\n" + "=" * 50)
    print("NOTA: OpenSky Network gratuito")
    print("- Limite: 400 chamadas/dia (anonimo)")
    print("- Com conta gratuita: 4000 chamadas/dia")
    print("- Dados atualizados a cada ~10 segundos")
    print("=" * 50)


if __name__ == "__main__":
    test_adsb_tracker()
